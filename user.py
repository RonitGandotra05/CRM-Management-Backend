import os
import uuid
import boto3
import psycopg2
import jwt
import sqlite3
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, File, Form, UploadFile, Header, Depends
from fastapi.security import OAuth2PasswordBearer
from datetime import datetime, timedelta
from io import BytesIO
from fastapi.middleware.cors import CORSMiddleware

# Load environment variables from .env file
load_dotenv()

# FastAPI App
app = FastAPI()

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Adjust this in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# JWT Secret Key and Algorithm (loaded from .env file)
SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = "HS256"

# AWS S3 Configuration (loaded from .env file)
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
S3_BUCKET = os.getenv("S3_BUCKET")
AWS_REGION = os.getenv("AWS_REGION")
DB_URL = os.getenv("DB_URL")
API_KEY = os.getenv("API_KEY")

# Initialize S3 client
s3 = boto3.client(
    's3',
    region_name=AWS_REGION,
    aws_access_key_id=AWS_ACCESS_KEY_ID,
    aws_secret_access_key=AWS_SECRET_ACCESS_KEY
)

# OAuth2 password bearer for token authentication
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")

# Database connection for users (SQLite)
def get_user_db_connection():
    conn = sqlite3.connect('users.db')
    return conn

# Database connection for remarks and blacklist (PostgreSQL)
def get_remarks_db_connection():
    conn = psycopg2.connect(DB_URL)
    return conn

# Function to verify email and password against the SQLite database
def verify_user_credentials(email: str, password: str):
    conn = get_user_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM user WHERE email = ? AND password = ?", (email, password))
    user = cursor.fetchone()
    conn.close()
    return user

# Function to create a new JWT token (without expiration)
def create_access_token(data: dict):
    to_encode = data.copy()
    # No expiration time is added to the payload
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

# Function to add a token to the blacklist
def blacklist_token(token: str, expires_at: datetime):
    conn = get_remarks_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO blacklisted_tokens (token, expires_at) VALUES (%s, %s)",
            (token, expires_at)
        )
        conn.commit()
    except psycopg2.errors.UniqueViolation:
        # Token is already blacklisted
        conn.rollback()
    except Exception as e:
        conn.rollback()
        print(f"Error blacklisting token: {e}")
        raise HTTPException(status_code=500, detail=f"Error blacklisting token: {str(e)}")
    finally:
        cursor.close()
        conn.close()

# Function to check if a token is blacklisted
def is_token_blacklisted(token: str):
    conn = get_remarks_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT 1 FROM blacklisted_tokens WHERE token = %s", (token,))
        result = cursor.fetchone()
        return result is not None
    except Exception as e:
        print(f"Error checking blacklist: {e}")
        raise HTTPException(status_code=500, detail=f"Error checking blacklist: {str(e)}")
    finally:
        cursor.close()
        conn.close()

# Endpoint for user login, returns JWT token
@app.post("/login")
async def login(email: str = Form(...), password: str = Form(...)):
    user = verify_user_credentials(email, password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    # Create JWT token upon successful login
    access_token = create_access_token(data={"sub": email})
    return {"access_token": access_token, "token_type": "bearer"}

# Endpoint for user logout
@app.post("/logout")
async def logout(token: str = Depends(oauth2_scheme)):
    # Decode the token
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM], options={"verify_exp": False})
    except jwt.PyJWTError:
        raise HTTPException(status_code=400, detail="Invalid token")
    # Set a future date for expiration (e.g., 10 years from now)
    expires_at = datetime.utcnow() + timedelta(days=365 * 10)
    # Add the token to the blacklist
    blacklist_token(token, expires_at)
    return {"message": "Successfully logged out"}

# Endpoint to fetch all asin_id, sku_id, and image_link from the asin_info table
@app.get("/get-asin-info/")
async def get_asin_info(token: str = Depends(oauth2_scheme)):
    # Check if token is blacklisted
    if is_token_blacklisted(token):
        raise HTTPException(status_code=403, detail="Token has been revoked")
    conn = get_remarks_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT asin_id, sku_id, image_link FROM asin_info")
        rows = cursor.fetchall()
        asin_info = [{"asin_id": row[0], "sku_id": row[1], "image_link": row[2]} for row in rows]
        return {"asin_info": asin_info}
    except Exception as e:
        print(f"Error fetching asin_info: {e}")
        raise HTTPException(status_code=500, detail=f"Error fetching asin_info: {str(e)}")
    finally:
        cursor.close()
        conn.close()

# Function to get the current user from the token
def get_current_user(token: str = Depends(oauth2_scheme)):
    # Check if token is blacklisted
    if is_token_blacklisted(token):
        raise HTTPException(status_code=403, detail="Token has been revoked")
    try:
        # Disable expiration verification
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM], options={"verify_exp": False})
        email = payload.get("sub")
        if email is None:
            raise HTTPException(status_code=403, detail="Invalid token")
        return email
    except jwt.PyJWTError:
        raise HTTPException(status_code=403, detail="Invalid token")

# Function to upload file to S3
def upload_to_s3(file_data: bytes, file_name: str, content_type: str):
    try:
        s3.put_object(
            Bucket=S3_BUCKET,
            Key=file_name,
            Body=file_data,
            ContentType=content_type,
        )
        file_url = f"https://{S3_BUCKET}.s3.{AWS_REGION}.amazonaws.com/{file_name}"
        return file_url
    except Exception as e:
        print(f"Error uploading to S3: {e}")
        raise HTTPException(status_code=500, detail=f"Error uploading to S3: {str(e)}")

# Function to save remark details to the PostgreSQL database
def save_to_db(asin: str, remarks: str, image_link: str, product_link: str):
    conn = get_remarks_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO remarks (asin, remarks, image_link, product_link) VALUES (%s, %s, %s, %s)",
            (asin, remarks, image_link, product_link)
        )
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"Error saving to database: {e}")
        raise HTTPException(status_code=500, detail=f"Error saving to database: {str(e)}")
    finally:
        cursor.close()
        conn.close()

# Endpoint for uploading remarks and media (protected by JWT)
@app.post("/upload-remarks/")
async def upload_remarks(
    asin: str = Form(...),
    remarks: str = Form(...),
    product_link: str = Form(...),
    file: UploadFile = File(...),
    current_user: str = Depends(get_current_user)  # Protect route with token
):
    try:
        file_content = await file.read()
        file_extension = os.path.splitext(file.filename)[1]
        file_name = f"screenshot-{uuid.uuid4()}{file_extension}"

        # Upload file to S3
        file_url = upload_to_s3(file_content, file_name, file.content_type)

        # Save the remark details in the database
        save_to_db(asin, remarks, file_url, product_link)

        return {"message": "Data uploaded successfully", "media_url": file_url}

    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {str(e)}")

# Endpoint to fetch all data from the remarks table
@app.get("/get-remarks/")
async def get_all_remarks(token: str = Depends(oauth2_scheme)):
    # Check if token is blacklisted
    if is_token_blacklisted(token):
        raise HTTPException(status_code=403, detail="Token has been revoked")

    conn = get_remarks_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT asin, remarks, image_link, product_link FROM remarks")
        rows = cursor.fetchall()

        remarks_data = [
            {
                "asin": row[0],
                "remarks": row[1],
                "image_link": row[2],
                "product_link": row[3]
            }
            for row in rows
        ]

        return {"remarks": remarks_data}
    except Exception as e:
        print(f"Error fetching remarks: {e}")
        raise HTTPException(status_code=500, detail=f"Error fetching remarks: {str(e)}")
    finally:
        cursor.close()
        conn.close()

# Root endpoint
@app.get("/")
async def root():
    return {"message": "Welcome to the CRM Remarks API!"}
