import os
from fastapi import FastAPI, HTTPException, Depends, File, UploadFile, Header
from fastapi.middleware.cors import CORSMiddleware
from pymongo import MongoClient
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from datetime import datetime
import httpx
import uuid
import cloudinary
import cloudinary.uploader
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = FastAPI(title="Objaverse API")

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # For production, specify allowed origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# MongoDB Connection
MONGO_URI = os.getenv("MONGO_URI")
client = MongoClient(MONGO_URI)
db = client.objaverse  # Database name

# Cloudinary Configuration
cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key=os.getenv("CLOUDINARY_API_KEY"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET")
)

# Pydantic Models
class Dimensions(BaseModel):
    width: Optional[float] = None
    height: Optional[float] = None
    depth: Optional[float] = None

class Metadata(BaseModel):
    dimensions: Optional[Dimensions] = None
    origin: Optional[str] = None
    creationDate: Optional[datetime] = None

class Image(BaseModel):
    imageId: str
    url: str
    angle: str

class Object3DBase(BaseModel):
    description: str
    category: str
    metadata: Optional[Metadata] = None

class Object3DCreate(Object3DBase):
    objectId: Optional[str] = None

class Object3DUpdate(BaseModel):
    description: Optional[str] = None
    category: Optional[str] = None
    metadata: Optional[Metadata] = None

class Object3D(Object3DBase):
    objectId: str
    images: List[Image] = []
    createdAt: datetime
    updatedAt: datetime

    class Config:
        orm_mode = True

# Authentication dependency
async def get_current_user(authorization: str = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    try:
        # Call auth service
        async with httpx.AsyncClient() as client:
            response = await client.get(
                "http://objaverse-auth-service:4000/me",
                headers={"Authorization": authorization}
            )
            if response.status_code != 200:
                raise HTTPException(status_code=401, detail="Invalid or expired token")
            return response.json()
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Authentication failed: {str(e)}")

# Routes
@app.get("/health")
async def health_check():
    return {"status": "ok"}

@app.get("/ready")
async def readiness_check():
    try:
        # Check MongoDB connection
        client.admin.command('ping')
        
        # Check auth service
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get("http://objaverse-auth-service:4000/health")
                if response.status_code != 200:
                    return {"status": "not ready", "message": "Auth service not ready"}
            except Exception:
                return {"status": "not ready", "message": "Auth service not ready"}
        
        return {"status": "ready"}
    except Exception as e:
        return {"status": "not ready", "error": str(e)}

@app.get("/api/objects", response_model=Dict[str, Any])
async def get_objects(page: int = 1, limit: int = 10, user=Depends(get_current_user)):
    skip = (page - 1) * limit
    
    objects = list(db.objects.find().skip(skip).limit(limit))
    total = db.objects.count_documents({})
    
    # Convert ObjectId to string for JSON serialization
    for obj in objects:
        obj["_id"] = str(obj["_id"])
    
    return {
        "success": True,
        "count": len(objects),
        "total": total,
        "page": page,
        "pages": (total + limit - 1) // limit,  # Ceiling division
        "data": objects
    }

@app.get("/api/objects/{object_id}", response_model=Dict[str, Any])
async def get_object(object_id: str, user=Depends(get_current_user)):
    obj = db.objects.find_one({"objectId": object_id})
    
    if not obj:
        raise HTTPException(status_code=404, detail="Object not found")
    
    # Convert ObjectId to string for JSON serialization
    obj["_id"] = str(obj["_id"])
    
    return {
        "success": True,
        "data": obj
    }

@app.post("/api/objects", response_model=Dict[str, Any])
async def create_object(object_data: Object3DCreate, user=Depends(get_current_user)):
    # Generate objectId if not provided
    if not object_data.objectId:
        object_data.objectId = str(uuid.uuid4())
    
    # Check if object already exists
    existing = db.objects.find_one({"objectId": object_data.objectId})
    if existing:
        raise HTTPException(status_code=400, detail="Object with this ID already exists")
    
    # Create object document
    now = datetime.utcnow()
    object_dict = object_data.dict()
    object_dict.update({
        "images": [],
        "createdAt": now,
        "updatedAt": now
    })
    
    result = db.objects.insert_one(object_dict)
    
    # Get the inserted object
    created_object = db.objects.find_one({"_id": result.inserted_id})
    created_object["_id"] = str(created_object["_id"])
    
    return {
        "success": True,
        "data": created_object
    }

@app.put("/api/objects/{object_id}", response_model=Dict[str, Any])
async def update_object(object_id: str, object_data: Object3DUpdate, user=Depends(get_current_user)):
    obj = db.objects.find_one({"objectId": object_id})
    
    if not obj:
        raise HTTPException(status_code=404, detail="Object not found")
    
    # Update fields if provided
    update_data = {k: v for k, v in object_data.dict(exclude_unset=True).items() if v is not None}
    
    if update_data:
        update_data["updatedAt"] = datetime.utcnow()
        db.objects.update_one({"objectId": object_id}, {"$set": update_data})
    
    # Get updated object
    updated_object = db.objects.find_one({"objectId": object_id})
    updated_object["_id"] = str(updated_object["_id"])
    
    return {
        "success": True,
        "data": updated_object
    }

@app.delete("/api/objects/{object_id}", response_model=Dict[str, Any])
async def delete_object(object_id: str, user=Depends(get_current_user)):
    obj = db.objects.find_one({"objectId": object_id})
    
    if not obj:
        raise HTTPException(status_code=404, detail="Object not found")
    
    # Delete images from Cloudinary
    for image in obj.get("images", []):
        if "url" in image:
            # Extract public ID from URL
            url_parts = image["url"].split("/")
            if "upload" in url_parts:
                upload_index = url_parts.index("upload")
                if upload_index + 2 < len(url_parts):  # Ensure there's a path after "upload"
                    public_id = "/".join(url_parts[upload_index+1:])
                    # Remove file extension
                    public_id = public_id.rsplit(".", 1)[0]
                    try:
                        cloudinary.uploader.destroy(public_id)
                    except Exception:
                        # Log error but continue
                        pass
    
    # Delete object
    db.objects.delete_one({"objectId": object_id})
    
    return {
        "success": True,
        "message": "Object deleted"
    }

@app.post("/api/objects/{object_id}/images", response_model=Dict[str, Any])
async def upload_image(
    object_id: str, 
    file: UploadFile = File(...), 
    angle: str = "front",
    user=Depends(get_current_user)
):
    obj = db.objects.find_one({"objectId": object_id})
    
    if not obj:
        raise HTTPException(status_code=404, detail="Object not found")
    
    # Upload to Cloudinary
    try:
        contents = await file.read()
        upload_result = cloudinary.uploader.upload(
            contents,
            folder="objaverse",
            transformation=[{"width": 500, "height": 500, "crop": "limit"}]
        )
        
        # Create image record
        image = {
            "imageId": upload_result["public_id"],
            "url": upload_result["secure_url"],
            "angle": angle
        }
        
        # Add image to object
        db.objects.update_one(
            {"objectId": object_id},
            {
                "$push": {"images": image},
                "$set": {"updatedAt": datetime.utcnow()}
            }
        )
        
        return {
            "success": True,
            "data": image
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to upload image: {str(e)}")

@app.get("/api/search", response_model=Dict[str, Any])
async def search_objects(query: str, user=Depends(get_current_user)):
    if not query:
        raise HTTPException(status_code=400, detail="Search query is required")
    
    objects = list(db.objects.find({
        "$or": [
            {"description": {"$regex": query, "$options": "i"}},
            {"category": {"$regex": query, "$options": "i"}}
        ]
    }).limit(20))
    
    # Convert ObjectId to string for JSON serialization
    for obj in objects:
        obj["_id"] = str(obj["_id"])
    
    return {
        "success": True,
        "count": len(objects),
        "data": objects
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 3000)))