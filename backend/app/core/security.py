from datetime import datetime, timedelta
from typing import Any, Union, Optional
from jose import jwt
from passlib.context import CryptContext
from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def get_password_hash(password: str) -> str:
    """
    Returns the hashed representation of a password using bcrypt.
    """
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verifies that a plain password matches its corresponding bcrypt hash.
    """
    return pwd_context.verify(plain_password, hashed_password)

def create_access_token(
    subject: Union[str, Any], role: str, expires_delta: Optional[timedelta] = None
) -> str:
    """
    Generates a secure JWT access token signed with the system secret key.
    Stores username/id and user roles in the token claims.
    """
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode = {
        "exp": expire,
        "sub": str(subject),
        "role": role
    }
    encoded_jwt = jwt.encode(to_encode, settings.JWT_SECRET, algorithm=settings.ALGORITHM)
    return encoded_jwt

def create_refresh_token(
    subject: Union[str, Any], role: str
) -> str:
    """
    Generates a refresh token with a longer duration (defaulting to 30 days).
    """
    expire = datetime.utcnow() + timedelta(days=30)
    to_encode = {
        "exp": expire,
        "sub": str(subject),
        "role": role,
        "refresh": True
    }
    encoded_jwt = jwt.encode(to_encode, settings.JWT_SECRET, algorithm=settings.ALGORITHM)
    return encoded_jwt

def verify_token(token: str) -> Optional[dict]:
    """
    Validates token signature and expiration.
    Returns the decoded token claims if valid, else None.
    """
    try:
        decoded_token = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.ALGORITHM])
        return decoded_token
    except Exception:
        return None
