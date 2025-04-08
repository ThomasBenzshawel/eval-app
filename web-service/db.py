import os
from pymongo import MongoClient
from dotenv import load_dotenv
import logging
from urllib.parse import quote_plus

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

class MongoDB:
    _instance = None
    _client = None
    _db = None

    @classmethod
    def get_instance(cls):
        """Singleton pattern to ensure only one database connection exists"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        """Initialize the MongoDB connection"""
        if self._client is not None:
            return

        try:
            # Get connection string from environment variable
            mongo_uri = os.getenv("MONGO_URI")
            
            if not mongo_uri:
                # If connection string is not provided directly, construct it from parts
                username = quote_plus(os.getenv("MONGO_USERNAME", ""))
                password = quote_plus(os.getenv("MONGO_PASSWORD", ""))
                host = os.getenv("MONGO_HOST", "localhost")
                port = os.getenv("MONGO_PORT", "27017")
                database = os.getenv("MONGO_DB", "objaverse")
                
                auth_source = os.getenv("MONGO_AUTH_SOURCE", "admin")
                replica_set = os.getenv("MONGO_REPLICA_SET", "")
                
                # Construct connection string
                if username and password:
                    mongo_uri = f"mongodb+srv://{username}:{password}@{host}/{database}?authSource={auth_source}"
                    if replica_set:
                        mongo_uri += f"&replicaSet={replica_set}"
                else:
                    mongo_uri = f"mongodb://{host}:{port}/{database}"
            
            # Connect to MongoDB
            logger.info(f"Connecting to MongoDB at {mongo_uri.split('@')[1] if '@' in mongo_uri else mongo_uri}")
            self._client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
            
            # Test connection
            self._client.admin.command('ping')
            logger.info("MongoDB connection successful")
            
            # Get database
            database_name = os.getenv("MONGO_DB", "objaverse")
            self._db = self._client[database_name]
            
        except Exception as e:
            logger.error(f"MongoDB connection failed: {str(e)}")
            raise

    @property
    def client(self):
        """Get the MongoDB client instance"""
        return self._client

    @property
    def db(self):
        """Get the database instance"""
        return self._db

    def close(self):
        """Close the connection"""
        if self._client:
            self._client.close()
            logger.info("MongoDB connection closed")

# Create convenience functions
def get_db():
    """Get the database instance"""
    return MongoDB.get_instance().db

def get_client():
    """Get the MongoDB client instance"""
    return MongoDB.get_instance().client

def close_connection():
    """Close the MongoDB connection"""
    MongoDB.get_instance().close()

# Example usage
if __name__ == "__main__":
    # Test the connection
    try:
        db = get_db()
        print(f"Connected to MongoDB. Available collections: {db.list_collection_names()}")
        
        # Add a test document
        result = db.test.insert_one({"test": "connection"})
        print(f"Inserted document with ID: {result.inserted_id}")
        
        # Find the document
        doc = db.test.find_one({"test": "connection"})
        print(f"Found document: {doc}")
        
        # Clean up
        db.test.delete_one({"test": "connection"})
        
    except Exception as e:
        print(f"Error: {str(e)}")
    finally:
        close_connection()
        print("Connection closed.")