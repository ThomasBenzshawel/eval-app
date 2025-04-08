import os
import cloudinary
import cloudinary.uploader
import cloudinary.api
from dotenv import load_dotenv
import logging
from typing import Dict, Any, Optional, List, Tuple
import tempfile

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

class CloudinaryService:
    """Service class for Cloudinary operations"""
    
    def __init__(self):
        """Initialize Cloudinary with configuration from environment variables"""
        cloudinary.config(
            cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
            api_key=os.getenv("CLOUDINARY_API_KEY"),
            api_secret=os.getenv("CLOUDINARY_API_SECRET")
        )
        self.folder = os.getenv("CLOUDINARY_FOLDER", "objaverse")
        logger.info(f"Cloudinary configured with cloud name: {os.getenv('CLOUDINARY_CLOUD_NAME')}")

    def upload_image(self, file_content: bytes, public_id: Optional[str] = None, 
                    tags: Optional[List[str]] = None, 
                    transformation: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Upload an image to Cloudinary
        
        Args:
            file_content: The binary content of the file
            public_id: Optional custom public ID
            tags: Optional list of tags
            transformation: Optional transformation instructions
            
        Returns:
            Dict containing upload result details
        """
        try:
            # Define upload parameters
            upload_params = {
                "folder": self.folder,
            }
            
            # Add optional parameters
            if public_id:
                upload_params["public_id"] = public_id
            
            if tags:
                upload_params["tags"] = tags
                
            if transformation:
                upload_params["transformation"] = transformation
            else:
                # Default transformation
                upload_params["transformation"] = [{"width": 500, "height": 500, "crop": "limit"}]
            
            # Create a temporary file to upload
            with tempfile.NamedTemporaryFile(delete=False) as temp_file:
                temp_file.write(file_content)
                temp_file_path = temp_file.name
            
            # Upload the file
            upload_result = cloudinary.uploader.upload(temp_file_path, **upload_params)
            
            # Clean up the temporary file
            os.unlink(temp_file_path)
            
            logger.info(f"Image uploaded successfully to Cloudinary: {upload_result['public_id']}")
            return upload_result
            
        except Exception as e:
            logger.error(f"Failed to upload image to Cloudinary: {str(e)}")
            raise

    def delete_image(self, public_id: str) -> Dict[str, Any]:
        """
        Delete an image from Cloudinary
        
        Args:
            public_id: The public ID of the image to delete
            
        Returns:
            Dict containing deletion result details
        """
        try:
            full_public_id = f"{self.folder}/{public_id}" if not public_id.startswith(f"{self.folder}/") else public_id
            result = cloudinary.uploader.destroy(full_public_id)
            logger.info(f"Image deleted from Cloudinary: {public_id}")
            return result
        except Exception as e:
            logger.error(f"Failed to delete image from Cloudinary: {str(e)}")
            raise

    def get_image_info(self, public_id: str) -> Dict[str, Any]:
        """
        Get information about an image
        
        Args:
            public_id: The public ID of the image
            
        Returns:
            Dict containing image details
        """
        try:
            full_public_id = f"{self.folder}/{public_id}" if not public_id.startswith(f"{self.folder}/") else public_id
            result = cloudinary.api.resource(full_public_id)
            return result
        except Exception as e:
            logger.error(f"Failed to get image info from Cloudinary: {str(e)}")
            raise

    def create_image_url(self, public_id: str, transformation: Optional[Dict[str, Any]] = None) -> str:
        """
        Create a URL for an image with optional transformations
        
        Args:
            public_id: The public ID of the image
            transformation: Optional transformation instructions
            
        Returns:
            The URL of the transformed image
        """
        try:
            full_public_id = f"{self.folder}/{public_id}" if not public_id.startswith(f"{self.folder}/") else public_id
            transform_options = transformation or {}
            url = cloudinary.CloudinaryImage(full_public_id).build_url(**transform_options)
            return url
        except Exception as e:
            logger.error(f"Failed to create image URL: {str(e)}")
            raise

    def extract_public_id_from_url(self, url: str) -> Tuple[str, str]:
        """
        Extract the public ID from a Cloudinary URL
        
        Args:
            url: The Cloudinary URL
            
        Returns:
            Tuple of (folder, public_id)
        """
        try:
            # Example URL: https://res.cloudinary.com/demo/image/upload/v1612345678/objaverse/sample.jpg
            parts = url.split('/')
            if 'upload' in parts:
                upload_index = parts.index('upload')
                # Check if there's a version segment after 'upload'
                if parts[upload_index + 1].startswith('v'):
                    # Skip the version segment
                    folder_and_file = '/'.join(parts[upload_index + 2:])
                else:
                    folder_and_file = '/'.join(parts[upload_index + 1:])
                
                # Split into folder and file
                if '/' in folder_and_file:
                    folder, public_id = folder_and_file.rsplit('/', 1)
                    # Remove file extension
                    if '.' in public_id:
                        public_id = public_id.rsplit('.', 1)[0]
                    return folder, public_id
                else:
                    # No folder
                    public_id = folder_and_file
                    if '.' in public_id:
                        public_id = public_id.rsplit('.', 1)[0]
                    return '', public_id
            
            raise ValueError(f"Could not extract public ID from URL: {url}")
        except Exception as e:
            logger.error(f"Failed to extract public ID from URL: {str(e)}")
            raise

# Create a singleton instance
cloudinary_service = CloudinaryService()

# Example usage
if __name__ == "__main__":
    # Test the service
    try:
        # Upload a test image
        with open("test_image.jpg", "rb") as f:
            content = f.read()
            result = cloudinary_service.upload_image(
                content, 
                tags=["test", "objaverse"],
                transformation={"width": 300, "height": 300, "crop": "fill"}
            )
            
            print(f"Uploaded image: {result['secure_url']}")
            
            # Get image info
            info = cloudinary_service.get_image_info(result['public_id'])
            print(f"Image info: {info}")
            
            # Create a URL with different transformation
            url = cloudinary_service.create_image_url(
                result['public_id'],
                transformation={"width": 200, "height": 200, "crop": "scale", "effect": "sepia"}
            )
            print(f"Transformed URL: {url}")
            
            # Delete the test image
            delete_result = cloudinary_service.delete_image(result['public_id'])
            print(f"Delete result: {delete_result}")
            
    except Exception as e:
        print(f"Error: {str(e)}")