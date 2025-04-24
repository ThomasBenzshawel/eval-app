import os
from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.middleware.cors import CORSMiddleware
from pymongo import MongoClient
from passlib.context import CryptContext
from jose import JWTError, jwt
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timedelta, timezone
import uuid
from typing import Dict, List
from dotenv import load_dotenv
from fastapi import Header


# Load environment variables
load_dotenv()

app = FastAPI(title="Auth Service")

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
db = client.objaverse_auth  # Database name

# Authentication settings
SECRET_KEY = os.getenv("JWT_SECRET")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_DAYS = 7

ADMIN_SECRET = os.getenv("ADMIN_SECRET")  


pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")

# Pydantic Models
class UserBase(BaseModel):
    email: str
    role: str = "researcher"  # Default role or can be set to "admin"

class UserCreate(UserBase):
    password: str

class User(UserBase):
    userId: str
    createdAt: datetime

    class Config:
        from_attributes = True 

class SessionBase(BaseModel):
    userId: str
    expiresAt: datetime
    isValid: bool = True

class Session(SessionBase):
    sessionId: str
    createdAt: datetime

class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    userId: Optional[str] = None
    sessionId: Optional[str] = None

# Helper functions
def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(days=ACCESS_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

async def get_current_user(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        userId: str = payload.get("sub")
        sessionId: str = payload.get("sessionId")
        if userId is None or sessionId is None:
            raise credentials_exception
        token_data = TokenData(userId=userId, sessionId=sessionId)
    except JWTError:
        raise credentials_exception
    
    # Verify session is valid
    session = db.sessions.find_one({
        "sessionId": sessionId,
        "isValid": True,
        "expiresAt": {"$gt": datetime.now(timezone.utc)}
    })
    if session is None:
        raise credentials_exception
    
    user = db.users.find_one({"userId": token_data.userId})
    if user is None:
        raise credentials_exception
    
    # Convert MongoDB document to User model
    user_model = {
        "userId": user["userId"],
        "email": user["email"],
        "role": user["role"],
        "createdAt": user["createdAt"]
    }
    
    return user_model

# Routes
@app.get("/health")
async def health_check():
    try:
        # Check MongoDB connection
        client.admin.command('ping')
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

#check if a user is an admin
async def check_admin_user(current_user: dict = Depends(get_current_user)):
    if current_user["role"] != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required"
        )
    return current_user

@app.post("/register", response_model=dict)
async def register(user_data: UserCreate, admin_user: dict = Depends(check_admin_user)):
    # Check if user exists
    existing_user = db.users.find_one({"email": user_data.email})
    if existing_user:
        raise HTTPException(status_code=400, detail="User already exists")
    
    # Hash password and create user
    hashed_password = get_password_hash(user_data.password)
    
    user_id = str(uuid.uuid4())
    user = {
        "userId": user_id,
        "email": user_data.email,
        "password": hashed_password,
        "role": user_data.role,
        "createdAt": datetime.now(timezone.utc)
    }
    
    db.users.insert_one(user)
    
    return {
        "message": "User registered successfully",
        "userId": user_id
    }

@app.post("/bootstrap-admin", response_model=dict)
async def create_first_admin(user_data: UserCreate, admin_secret: str = Header(...)):
    # Verify admin secret
    if not ADMIN_SECRET or admin_secret != ADMIN_SECRET:
        # Use a generic error message for security
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Unauthorized"
        )
    
    # Check if any admin users already exist
    existing_admin = db.users.find_one({"role": "admin"})
    if existing_admin:
        raise HTTPException(
            status_code=400, 
            detail="Admin user already exists. This endpoint can only be used once."
        )
    
    # Hash password and create admin user
    hashed_password = get_password_hash(user_data.password)
    
    user_id = str(uuid.uuid4())
    user = {
        "userId": user_id,
        "email": user_data.email,
        "password": hashed_password,
        "role": "admin",  # Force admin role regardless of what was provided
        "createdAt": datetime.now(timezone.utc)
    }
    
    db.users.insert_one(user)
    
    return {
        "message": "Admin user created successfully",
        "userId": user_id
    }

@app.post("/login", response_model=Token)
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    # Find user
    user = db.users.find_one({"email": form_data.username})
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Verify password
    if not verify_password(form_data.password, user["password"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Create session
    session_id = str(uuid.uuid4())
    expires_at = datetime.now(timezone.utc) + timedelta(days=ACCESS_TOKEN_EXPIRE_DAYS)
    
    session = {
        "sessionId": session_id,
        "userId": user["userId"],
        "isValid": True,
        "expiresAt": expires_at,
        "createdAt": datetime.now(timezone.utc)
    }
    
    db.sessions.insert_one(session)
    
    # Create JWT token
    access_token = create_access_token(
        data={"sub": user["userId"], "sessionId": session_id},
        expires_delta=timedelta(days=ACCESS_TOKEN_EXPIRE_DAYS)
    )
    
    return {"access_token": access_token, "token_type": "bearer"}

@app.post("/logout")
async def logout(current_user: dict = Depends(get_current_user)):
    # Get token from authorization header
    # Extract session ID from token and invalidate it
    try:
        token = current_user.get("token")
        if token:
            payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
            session_id = payload.get("sessionId")
            if session_id:
                db.sessions.update_one(
                    {"sessionId": session_id},
                    {"$set": {"isValid": False}}
                )
        
        return {"message": "Logout successful"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Logout failed: {str(e)}")

@app.get("/me", response_model=dict)
async def read_users_me(current_user: dict = Depends(get_current_user)):
    return {
        "userId": current_user["userId"],
        "email": current_user["email"],
        "role": current_user["role"]
    }

@app.get("/users/{user_id}", response_model=dict)
async def get_user(user_id: str, admin_user: dict = Depends(check_admin_user)):
    # Only admins can access user details
    user = db.users.find_one({"userId": user_id}, {"password": 0})  # Exclude password
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Convert ObjectId to string for JSON serialization
    if "_id" in user:
        user["_id"] = str(user["_id"])
    
    return user

@app.get("/users", response_model=Dict[str, List[dict]])
async def get_users(admin_user: dict = Depends(check_admin_user)):
    # Only admins can see the user list
    users = list(db.users.find({}, {"password": 0}))  # Exclude passwords
    
    # Convert ObjectId to string for JSON serialization
    for user in users:
        if "_id" in user:
            user["_id"] = str(user["_id"])
    
    return {"data": users}


@app.put("/register/{user_id}", response_model=dict)
async def update_user(user_id: str, user_data: dict, admin_user: dict = Depends(check_admin_user)):
    # Check if user exists
    existing_user = db.users.find_one({"userId": user_id})
    if not existing_user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Check if this is the last admin
    if existing_user["role"] == "admin" and user_data.get("role") != "admin":
        admin_count = db.users.count_documents({"role": "admin"})
        if admin_count <= 1:
            raise HTTPException(
                status_code=400,
                detail="Cannot change role of the last admin user"
            )
    
    # Prepare update data
    update_data = {}
    
    # Update email if provided
    if "email" in user_data:
        # Check if email already exists for another user
        email_user = db.users.find_one({"email": user_data["email"], "userId": {"$ne": user_id}})
        if email_user:
            raise HTTPException(status_code=400, detail="Email already in use")
        update_data["email"] = user_data["email"]
    
    # Update role if provided
    if "role" in user_data:
        if user_data["role"] not in ["user", "admin"]:
            raise HTTPException(status_code=400, detail="Invalid role")
        update_data["role"] = user_data["role"]
    
    # Update password if provided
    if "password" in user_data and user_data["password"]:
        update_data["password"] = get_password_hash(user_data["password"])
    
    # Update user
    if update_data:
        result = db.users.update_one(
            {"userId": user_id},
            {"$set": update_data}
        )
        
        if result.modified_count == 0:
            raise HTTPException(status_code=400, detail="Failed to update user")
    
    return {"message": "User updated successfully"}

@app.delete("/register/{user_id}", response_model=dict)
async def delete_user(user_id: str, admin_user: dict = Depends(check_admin_user)):
    # Make sure it's not the last admin
    if admin_user["userId"] == user_id:
        raise HTTPException(
            status_code=400,
            detail="Cannot delete your own account"
        )
    
    # Check if this is the last admin
    user_to_delete = db.users.find_one({"userId": user_id})
    if not user_to_delete:
        raise HTTPException(status_code=404, detail="User not found")
        
    if user_to_delete["role"] == "admin":
        admin_count = db.users.count_documents({"role": "admin"})
        if admin_count <= 1:
            raise HTTPException(
                status_code=400,
                detail="Cannot delete the last admin account"
            )
    
    # Delete the user
    result = db.users.delete_one({"userId": user_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Also delete any sessions for this user
    db.sessions.delete_many({"userId": user_id})
    
    return {"message": "User deleted successfully"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 4000)), log_level="info", workers=4)