import os
from fastapi import FastAPI, HTTPException, Depends, File, UploadFile, Header, Body
from fastapi.middleware.cors import CORSMiddleware
from pymongo import MongoClient
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
import datetime as dt
from datetime import datetime
import httpx
import uuid
import cloudinary
import cloudinary.uploader
from dotenv import load_dotenv
import logging

# Load environment variables
load_dotenv()
AUTH_SERVICE_URL = os.getenv("AUTH_SERVICE_URL", "http://localhost:4000")
app = FastAPI(title="Objaverse API")

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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
class Rating(BaseModel):
    userId: str
    score: int  # 1-5 rating
    comment: Optional[str] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(dt.timezone.utc))

class Assignment(BaseModel):
    userId: str
    assignedAt: datetime = Field(default_factory=lambda: datetime.now(dt.timezone.utc))
    completedAt: Optional[datetime] = None

class Object3DBase(BaseModel):
    description: str
    category: str
    metadata: Optional[Metadata] = None
    assignments: List[Assignment] = []  

class Object3D(Object3DBase):
    objectId: str
    images: List[Image] = []
    ratings: List[Rating] = []
    averageRating: Optional[float] = None
    createdAt: datetime
    updatedAt: datetime

    class Config:
        from_attributes = True 

# Authentication dependency
async def get_current_user(authorization: str = Header(None)):
    if not authorization:
        logging.error("No authorization header provided")
        raise HTTPException(status_code=401, detail="Authentication required")
    
    try:
        # Call auth service with more detailed logging
        logging.info(f"Validating token with auth service at {AUTH_SERVICE_URL}/me")
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{AUTH_SERVICE_URL}/me",
                headers={"Authorization": authorization}
            )
            if response.status_code != 200:
                logging.error(f"Auth service returned status code {response.status_code}: {response.text}")
                raise HTTPException(status_code=401, detail="Invalid or expired token")
            return response.json()
    except Exception as e:
        logging.error(f"Exception during auth validation: {str(e)}")
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
    now = datetime.now(dt.timezone.utc)
    object_dict = object_data
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
    update_data = {k: v for k, v in object_data.model_dump(exclude_unset=True).items() if v is not None}
    
    if update_data:
        update_data["updatedAt"] = datetime.now(dt.timezone.utc)
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
    angle: str = "front"
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
            transformation=[{"width": 500, "height": 500, "crop": "limit"}],
            overwrite=True # Overwrite existing images with the same public ID
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
                "$set": {"updatedAt": datetime.now(dt.timezone.utc)}
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

@app.post("/api/objects/{object_id}/batch-images", response_model=Dict[str, Any])
async def upload_multiple_images(
    object_id: str, 
    files: List[UploadFile] = File(...),
    angles: Optional[List[str]] = None,
    user=Depends(get_current_user)
):
    """
    Upload multiple images for a 3D object at once.
    Optionally provide a list of angles corresponding to each image.
    """
    obj = db.objects.find_one({"objectId": object_id})
    
    if not obj:
        raise HTTPException(status_code=404, detail="Object not found")
    
    # Set default angles if not provided
    if not angles:
        angles = ["unspecified"] * len(files)
    elif len(angles) != len(files):
        raise HTTPException(status_code=400, detail="Number of angles must match number of files")
    
    uploaded_images = []
    
    # Upload each image to Cloudinary
    for i, file in enumerate(files):
        try:
            contents = await file.read()
            upload_result = cloudinary.uploader.upload(
                contents,
                folder=f"objaverse/{object_id}",  # Organize by object ID
                transformation=[{"width": 500, "height": 500, "crop": "limit"}]
            )
            
            # Create image record
            image = {
                "imageId": upload_result["public_id"],
                "url": upload_result["secure_url"],
                "angle": angles[i]
            }
            
            uploaded_images.append(image)
            
        except Exception as e:
            # Continue with other uploads even if one fails
            logging.error(f"Failed to upload image {i}: {str(e)}")
    
    # Add all successful uploads to the object
    if uploaded_images:
        db.objects.update_one(
            {"objectId": object_id},
            {
                "$push": {"images": {"$each": uploaded_images}},
                "$set": {"updatedAt": datetime.now(dt.timezone.utc)}
            }
        )
    
    return {
        "success": True,
        "count": len(uploaded_images),
        "data": uploaded_images
    }

# used for bulk assignment of objects to users
@app.post("/api/bulk-assign", response_model=Dict[str, Any])
async def bulk_assign_objects(
    assignments: List[Dict[str, str]] = Body(...),
    user=Depends(get_current_user)
):
    """Bulk assign objects to users for evaluation"""
    results = {
        "success": [],
        "failed": []
    }
    
    for assignment in assignments:
        if "objectId" not in assignment or "userId" not in assignment:
            results["failed"].append({
                "assignment": assignment,
                "reason": "Missing objectId or userId"
            })
            continue
        
        object_id = assignment["objectId"]
        user_id = assignment["userId"]
        
        # Check if object exists
        obj = db.objects.find_one({"objectId": object_id})
        if not obj:
            results["failed"].append({
                "assignment": assignment,
                "reason": "Object not found"
            })
            continue
        
        # Check if user is already assigned
        already_assigned = db.objects.find_one({
            "objectId": object_id,
            "assignments.userId": user_id
        })
        
        if already_assigned:
            results["success"].append(assignment)
            continue
        
        # Add assignment
        try:
            db.objects.update_one(
                {"objectId": object_id},
                {
                    "$push": {
                        "assignments": {
                            "userId": user_id,
                            "assignedAt": datetime.now(dt.timezone.utc)
                        }
                    },
                    "$set": {"updatedAt": datetime.now(dt.timezone.utc)}
                }
            )
            results["success"].append(assignment)
        except Exception as e:
            results["failed"].append({
                "assignment": assignment,
                "reason": str(e)
            })
    
    return {
        "success": True,
        "successful_count": len(results["success"]),
        "failed_count": len(results["failed"]),
        "data": results
    }


@app.post("/api/objects/{object_id}/assign", response_model=Dict[str, Any])
async def assign_object_to_user(
    object_id: str,
    userId: str = Body(...),
    user=Depends(get_current_user)
):
    """Assign an object to a user for evaluation"""
    obj = db.objects.find_one({"objectId": object_id})
    
    if not obj:
        raise HTTPException(status_code=404, detail="Object not found")
    
    # Check if user is already assigned
    already_assigned = db.objects.find_one({
        "objectId": object_id,
        "assignments.userId": userId
    })
    
    if already_assigned:
        return {
            "success": False,
            "message": f"Object {object_id} already assigned to user {userId}"
        }
    
    
    # Add user to assignments array
    assignment = {
        "userId": userId,
        "assignedAt": datetime.now(dt.timezone.utc)
    }
    
    db.objects.update_one(
        {"objectId": object_id},
        {
            "$push": {"assignments": assignment},
            "$set": {"updatedAt": datetime.now(dt.timezone.utc)}
        }
    )
    
    return {
        "success": True,
        "message": f"Object {object_id} assigned to user {userId}"
    }


@app.get("/api/assignments", response_model=Dict[str, Any])
async def get_user_assignments(
    userId: str,
    page: int = 1,
    limit: int = 10,
    user=Depends(get_current_user)
):
    """Get objects assigned to a specific user that haven't been rated yet"""
    skip = (page - 1) * limit
    
    query = {
        "assignments.userId": userId,
        "$or": [
            {"ratings": {"$exists": False}},
            {"ratings": {"$not": {"$elemMatch": {"userId": userId}}}}
        ]
    }
    
    objects = list(db.objects.find(query).skip(skip).limit(limit))
    total = db.objects.count_documents(query)
    
    # Process each object to ensure proper image URLs
    for obj in objects:
        obj["_id"] = str(obj["_id"])

        # Ensure images property exists
        if "images" not in obj or not obj["images"]:
            # Create a default Cloudinary URL using the object ID
            object_id = obj["objectId"]
            default_image = {
                "imageId": f"objaverse/{object_id}",
                "url": f"https://res.cloudinary.com/objaverse-kedziora/image/upload/objects/{object_id}/{object_id}_{object_id}_front.jpg",
                "angle": "front"
            }
            obj["images"] = [default_image]
        else:
            # Ensure each image has the correct Cloudinary URL format
            for img in obj["images"]:
                if "url" not in img or not img["url"].startswith("https://res.cloudinary.com"):
                    object_id = obj["objectId"]
                    img_id = img.get("imageId", f"{object_id}_{object_id}_front")
                    img["url"] = f"https://res.cloudinary.com/objaverse-kedziora/image/upload/objects/{object_id}/{img_id}.jpg"
    
    return {
        "success": True,
        "count": len(objects),
        "total": total,
        "page": page,
        "pages": (total + limit - 1) // limit,
        "data": objects
    }

@app.post("/api/assignments", response_model=Dict[str, Any])
async def assign_objects_to_users(
    assignment: Dict[str, str] = Body(...),  # Changed from List to Dict
    user=Depends(get_current_user)
):
    # Wrap the single assignment in a list #TODO MAKE THIS ACTUALLY A ONE ITEM INPUT
    assignments = [assignment]

    """Assign multiple objects to users"""
    results = {
        "success": [],
        "failed": []
    }
    
    for assignment in assignments:
        object_id = assignment["objectId"]
        user_id = assignment["userId"]
        
        # Check if object exists
        obj = db.objects.find_one({"objectId": object_id})
        if not obj:
            results["failed"].append({
                "assignment": assignment,
                "reason": "Object not found"
            })
            continue
        
        # Check if user is already assigned
        already_assigned = db.objects.find_one({
            "objectId": object_id,
            "assignments.userId": user_id
        })
        
        if already_assigned:
            results["success"].append(assignment)
            continue
        
        # Add assignment
        try:
            db.objects.update_one(
                {"objectId": object_id},
                {
                    "$push": {
                        "assignments": {
                            "userId": user_id,
                            "assignedAt": datetime.now(dt.timezone.utc)
                        }
                    },
                    "$set": {"updatedAt": datetime.now(dt.timezone.utc)}
                }
            )
            results["success"].append(assignment)
        except Exception as e:
            results["failed"].append({
                "assignment": assignment,
                "reason": str(e)
            })
    
    return {
        "success": True,
        "successful_count": len(results["success"]),
        "failed_count": len(results["failed"]),
        "data": results
    }

@app.post("/api/completed", response_model=Dict[str, Any])
async def get_completed_evaluations(
    request_data: Dict[str, str],
    page: int = 1,
    limit: int = 10,
    user=Depends(get_current_user)
):
    """Get objects that have been rated by the specified user with all required metrics"""
    userId = request_data.get("userId")
    if not userId:
        raise HTTPException(status_code=400, detail="userId is required")
   
    skip = (page - 1) * limit
   
    # query to include both standard ratings and unknown objects
    query = {
        "assignments.userId": userId,
        "ratings": {
            "$elemMatch": {
                "userId": userId,
                "$or": [
                    # Standard ratings with accuracy and completeness
                    {
                        "accuracy": {"$exists": True},
                        "completeness": {"$exists": True}
                    },
                    # Unknown objects
                    {
                        "metrics.unknown_object": True
                    },
                    # deprecated format or partial evaluations
                    {
                        "score": {"$exists": True}
                    }
                ]
            }
        }
    }
   
    objects = list(db.objects.find(query).skip(skip).limit(limit))
    total = db.objects.count_documents(query)
   
    # Process each object
    for obj in objects:
        obj["_id"] = str(obj["_id"])
       
        # Mark assignment as completed if not already
        for assignment in obj.get("assignments", []):
            if assignment.get("userId") == userId and not assignment.get("completedAt"):
                db.objects.update_one(
                    {
                        "objectId": obj["objectId"],
                        "assignments.userId": userId
                    },
                    {
                        "$set": {
                            "assignments.$.completedAt": datetime.now(dt.timezone.utc)
                        }
                    }
                )
        
        # Extract user's ratings from the single rating document
        user_ratings = {
            "accuracy": 0,
            "completeness": 0, 
            "clarity": 0
        }
        
        is_unknown_object = False
        
        # Find this user's rating document
        for rating in obj.get("ratings", []):
            if rating.get("userId") == userId:
                # Check if this is an unknown object
                if rating.get("metrics", {}).get("unknown_object", False):
                    is_unknown_object = True
                    # Set default values for unknown objects
                    user_ratings = {
                        "accuracy": 0,
                        "completeness": 0,
                        "clarity": 0
                    }
                else:
                    # Extract metrics from the rating document
                    user_ratings["accuracy"] = rating.get("accuracy", rating.get("score", 0))
                    user_ratings["completeness"] = rating.get("completeness", 0)
                    user_ratings["clarity"] = rating.get("clarity", 0)
                break
        
        # Add user's ratings to the object for easier access in templates
        obj["user_ratings"] = user_ratings
        obj["is_unknown_object"] = is_unknown_object

    
    print(f"Completed evaluations: {len(objects)}")
    return {
        "success": True,
        "count": len(objects),
        "total": total,
        "page": page,
        "pages": (total + limit - 1) // limit,
        "data": objects
    }


@app.get("/api/completed/{object_id}", response_model=Dict[str, Any])
async def get_completed_evaluation(
    object_id: str,
    user=Depends(get_current_user)
):
    """Get details for a specific rated object"""
    obj = db.objects.find_one({"objectId": object_id})
    
    if not obj:
        raise HTTPException(status_code=404, detail="Object not found")
    
    # Convert ObjectId to string for JSON serialization
    obj["_id"] = str(obj["_id"])
    
    # Extract the user's rating if it exists
    if "ratings" in obj:
        user_rating = next((r for r in obj["ratings"] if r.get("userId") == user["userId"]), None)
        if user_rating:
            obj["userRating"] = user_rating
    
    return {
        "success": True,
        "data": obj
    }

@app.post("/api/objects/{object_id}/rate", response_model=Dict[str, Any])
async def rate_object_description(
    object_id: str,
    rating_data: Dict[str, Any] = Body(...),
    user=Depends(get_current_user)
):
    """Rate an object's description"""

    # Log the rating data for debugging
    logging.info(f"Rating data: {rating_data}")
    
    # Check if object exists
    obj = db.objects.find_one({"objectId": object_id})
    if not obj:
        raise HTTPException(status_code=404, detail="Object not found")
   
    # Check for unknown object flag in metrics
    is_unknown_object = False
    if "metrics" in rating_data and rating_data.get("metrics", {}).get("unknown_object", False):
        is_unknown_object = True
   
    # Validate rating (skip validation for unknown objects)
    if not is_unknown_object and ("score" not in rating_data or not isinstance(rating_data["score"], int) or not (1 <= rating_data["score"] <= 5)):
        raise HTTPException(status_code=400, detail="Rating must be an integer between 1 and 5")
    
    # Get additional metrics if available
    metrics = rating_data.get("metrics", {})
    
    # Create the rating document
    now = datetime.now(dt.timezone.utc)
    primary_rating = {
        "userId": user["userId"],
        "score": rating_data["score"],
        "timestamp": now
    }
   
    # Store metrics if provided
    if "metrics" in rating_data:
        primary_rating["metrics"] = rating_data["metrics"]
   
    # Add comment if provided
    if "comment" in rating_data and rating_data["comment"]:
        primary_rating["comment"] = rating_data["comment"]
    
    # Add metrics as separate fields in the primary rating
    if metrics:
        for metric_name, metric_value in metrics.items():
            if isinstance(metric_value, (int, bool)) or metric_name == "unknown_object":
                primary_rating[metric_name] = metric_value
    
    # First remove any existing rating from this user
    db.objects.update_one(
        {"objectId": object_id},
        {"$pull": {"ratings": {"userId": user["userId"]}}}
    )
    
    # Then add the new rating in a separate operation
    db.objects.update_one(
        {"objectId": object_id},
        {
            "$push": {"ratings": primary_rating},
            "$set": {"updatedAt": now}
        }
    )
    
    # Mark assignment as completed
    db.objects.update_one(
        {"objectId": object_id, "assignments.userId": user["userId"]},
        {
            "$set": {
                "assignments.$.completedAt": now
            }
        }
    )
    
    # Update average ratings
    updated_obj = db.objects.find_one({"objectId": object_id})
    ratings = updated_obj.get("ratings", [])
    
    if ratings:
        # Calculate overall average
        all_scores = [r["score"] for r in ratings]
        avg_rating = round(sum(all_scores) / len(all_scores), 2)
        
        # Calculate averages for each metric if available
        avg_ratings = {"overall": avg_rating}
        
        # Check if we have metric-specific ratings
        metric_names = ["accuracy", "completeness", "clarity"]
        for metric in metric_names:
            metric_scores = [r.get(metric, r["score"]) for r in ratings if metric in r or "score" in r]
            if metric_scores:
                avg_ratings[metric] = round(sum(metric_scores) / len(metric_scores), 2)
        
        # Update in database
        db.objects.update_one(
            {"objectId": object_id},
            {"$set": {
                "averageRatings": avg_ratings,
                "averageRating": avg_rating
            }}
        )
    
    return {
        "success": True,
        "message": "Rating submitted successfully",
        "data": primary_rating
    }

@app.get("/api/objects/{object_id}/ratings", response_model=Dict[str, Any])
async def get_object_ratings(object_id: str, user=Depends(get_current_user)):
    """Get all ratings for an object"""
    obj = db.objects.find_one({"objectId": object_id})
    
    if not obj:
        raise HTTPException(status_code=404, detail="Object not found")
    
    ratings = obj.get("ratings", [])
    avg_rating = obj.get("averageRating")
    
    return {
        "success": True,
        "data": {
            "ratings": ratings,
            "averageRating": avg_rating,
            "count": len(ratings)
        }
    }

@app.delete("/api/ratings/{object_id}/{user_id}", response_model=Dict[str, Any])
async def delete_rating(
    object_id: str,
    user_id: str,
    user=Depends(get_current_user)
):
    """Delete a specific user's rating for an object"""
    # Check if user is admin
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Only admins can delete ratings")
    
    # Check if object exists
    obj = db.objects.find_one({"objectId": object_id})
    if not obj:
        raise HTTPException(status_code=404, detail="Object not found")
    
    # Check if rating exists
    ratings = obj.get("ratings", [])
    rating_exists = any(r.get("userId") == user_id for r in ratings)
    
    if not rating_exists:
        raise HTTPException(status_code=404, detail=f"No rating found for user {user_id}")
    
    # Remove the rating
    db.objects.update_one(
        {"objectId": object_id},
        {
            "$pull": {"ratings": {"userId": user_id}},
            "$set": {"updatedAt": datetime.now(dt.timezone.utc)}
        }
    )
    
    # Update average ratings
    updated_obj = db.objects.find_one({"objectId": object_id})
    updated_ratings = updated_obj.get("ratings", [])
    
    if updated_ratings:
        # Calculate overall average
        all_scores = [r["score"] for r in updated_ratings if "score" in r]
        avg_rating = round(sum(all_scores) / len(all_scores), 2) if all_scores else 0
        
        # Calculate averages for each metric if available
        avg_ratings = {"overall": avg_rating}
        
        # Check if we have metric-specific ratings
        metric_names = ["accuracy", "completeness", "clarity"]
        for metric in metric_names:
            metric_scores = [r.get(metric, r["score"]) for r in updated_ratings if metric in r or "score" in r]
            if metric_scores:
                avg_ratings[metric] = round(sum(metric_scores) / len(metric_scores), 2)
        
        # Update in database
        db.objects.update_one(
            {"objectId": object_id},
            {"$set": {
                "averageRatings": avg_ratings,
                "averageRating": avg_rating
            }}
        )
    else:
        # No ratings left, remove averages
        db.objects.update_one(
            {"objectId": object_id},
            {"$unset": {
                "averageRatings": "",
                "averageRating": ""
            }}
        )
    
    return {
        "success": True,
        "message": f"Rating for user {user_id} deleted successfully",
    }




if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 3000)), log_level="info", workers=4)