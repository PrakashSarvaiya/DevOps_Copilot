from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.database.db import get_db
from app.models.models import User
from app.schemas.schemas import UserCreate, UserResponse, Token, LoginRequest
from app.core.security import verify_password, get_password_hash, create_access_token, create_refresh_token, verify_token
from app.api.deps import get_current_user

router = APIRouter()

@router.post("/register", response_model=Token, status_code=status.HTTP_201_CREATED)
async def register(user_in: UserCreate, db: AsyncSession = Depends(get_db)):
    # Check if username exists
    result_username = await db.execute(select(User).filter(User.username == user_in.username))
    if result_username.scalars().first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already registered"
        )
    
    # Check if email exists
    result_email = await db.execute(select(User).filter(User.email == user_in.email))
    if result_email.scalars().first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )
    
    # Create user
    hashed_password = get_password_hash(user_in.password)
    db_user = User(
        username=user_in.username,
        email=user_in.email,
        hashed_password=hashed_password,
        role=user_in.role
    )
    db.add(db_user)
    await db.commit()
    await db.refresh(db_user)
    
    # Generate tokens
    access_token = create_access_token(subject=db_user.username, role=db_user.role)
    refresh_token = create_refresh_token(subject=db_user.username, role=db_user.role)
    return Token(access_token=access_token, refresh_token=refresh_token)

@router.post("/login", response_model=Token)
async def login(credentials: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).filter(User.username == credentials.username))
    user = result.scalars().first()
    if not user or not verify_password(credentials.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Incorrect username or password"
        )
    
    # Generate tokens
    access_token = create_access_token(subject=user.username, role=user.role)
    refresh_token = create_refresh_token(subject=user.username, role=user.role)
    return Token(access_token=access_token, refresh_token=refresh_token)

@router.post("/refresh", response_model=Token)
async def refresh_access_token(refresh_token: str, db: AsyncSession = Depends(get_db)):
    payload = verify_token(refresh_token)
    if not payload or not payload.get("refresh"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token"
        )
    
    username = payload.get("sub")
    role = payload.get("role")
    
    # Verify user still exists
    result = await db.execute(select(User).filter(User.username == username))
    user = result.scalars().first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found"
        )
        
    access_token = create_access_token(subject=username, role=role)
    new_refresh_token = create_refresh_token(subject=username, role=role)
    return Token(access_token=access_token, refresh_token=new_refresh_token)

@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    return current_user
