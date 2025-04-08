# Install required packages
# pip install fastapi uvicorn pymongo python-jose[cryptography] passlib[bcrypt] pydantic python-dotenv python-multipart

import os
from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.middleware.cors import CORSMiddleware
from pymongo import MongoClient
from passlib.context import CryptContext
from jose import JWTError, jwt
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timedelta
import uuid
from dotenv import load_dotenv

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

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

# Pydantic Models
class UserBase(BaseModel):
    email: str
    role: str = "researcher"  # Default role

class UserCreate(UserBase):
    password: str

class User(UserBase):
    userId: str
    createdAt: datetime

    class Config:
        orm_mode = True

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
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(days=ACCESS_TOKEN_EXPIRE_DAYS)
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
        "expiresAt": {"$gt": datetime.utcnow()}
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

@app.post("/register", response_model=dict)
async def register(user_data: UserCreate):
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
        "createdAt": datetime.utcnow()
    }
    
    db.users.insert_one(user)
    
    return {
        "message": "User registered successfully",
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
    expires_at = datetime.utcnow() + timedelta(days=ACCESS_TOKEN_EXPIRE_DAYS)
    
    session = {
        "sessionId": session_id,
        "userId": user["userId"],
        "isValid": True,
        "expiresAt": expires_at,
        "createdAt": datetime.utcnow()
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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 4000)))