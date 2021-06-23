import os
import datetime
from enum import Enum
from typing import Optional
import secrets
import motor.motor_asyncio
from bson import ObjectId
from dotenv import load_dotenv
from pydantic import BaseModel, Field, EmailStr, AnyHttpUrl, validator
from auth import AuthHandler

load_dotenv()
auth_handler = AuthHandler()


class MongoDBConnection:
	def __init__(self):
		self.client = motor.motor_asyncio.AsyncIOMotorClient(os.getenv('MONGODB_URI'))
		self.db = self.client.multiorder


class PyObjectId(ObjectId):
	@classmethod
	def __get_validators__(cls):
		yield cls.validate
	
	@classmethod
	def validate(cls, v):
		if not ObjectId.is_valid(v):
			raise ValueError("Invalid objectid")
		return ObjectId(v)
	
	@classmethod
	def __modify_schema__(cls, field_schema):
		field_schema.update(type="string")


class ReceiptNoteStatus(str, Enum):
	completed: str = "COMPLETED"
	uncompleted: str = "UNCOMPLETED"


class CreateReceiptNote(BaseModel):
	receipt_id: str
	note: str
	status: ReceiptNoteStatus = Field(default=ReceiptNoteStatus.uncompleted)
	

class UpdateReceiptNote(BaseModel):
	receipt_id: str
	note: Optional[str]
	status: Optional[ReceiptNoteStatus]


class ReceiptNote(BaseModel):
	id: PyObjectId = Field(default_factory=PyObjectId, alias="_id")
	receipt_id: str
	created_by: str
	updated_by: Optional[str]
	note: str
	status: ReceiptNoteStatus = Field(default=ReceiptNoteStatus.uncompleted)
	
	class Config:
		allow_population_by_field_name = True
		arbitrary_types_allowed = True
		validate_assignment = True
		json_encoders = {ObjectId: str}


class InvitationEmail(BaseModel):
	id: PyObjectId = Field(default_factory=PyObjectId, alias="_id")
	email: EmailStr = Field(allow_mutation=False, unique=True)
	verification_code: str = None
	is_registered: bool = False
	
	@validator('verification_code', pre=True, always=True)
	def generate_verification_code(cls, v) -> str:
		return secrets.token_urlsafe(16)
	
	@validator('is_registered', pre=True, always=True)
	def check_is_registered(cls, v):
		return False
	
	class Config:
		allow_population_by_field_name = True
		arbitrary_types_allowed = True
		validate_assignment = True
		json_encoders = {ObjectId: str}


class User(BaseModel):
	id: PyObjectId = Field(default_factory=PyObjectId, alias="_id")
	email: EmailStr = Field(unique=True)
	username: str = Field(unique=True)
	password: str = Field(...)
	is_admin: bool = False
	verification_code: str = Field(...)
	
	@validator('is_admin', pre=True, always=True)
	def default_is_admin(cls, v):
		if v:
			return False
		return False
	
	@validator('password', pre=True, always=True)
	def hash_password(cls, v):
		return auth_handler.get_password_hash(v)
	
	class Config:
		allow_mutation = False
		allow_population_by_field_name = True
		arbitrary_types_allowed = True
		validate_assignment = True
		json_encoders = {ObjectId: str}


class EtsyShopConnection(BaseModel):
	id: PyObjectId = Field(default_factory=PyObjectId, alias="_id")
	app_key: Optional[str]
	app_secret: Optional[str]
	etsy_shop_name: Optional[str]
	etsy_shop_id: Optional[str]
	shop_icon_url: Optional[AnyHttpUrl]
	shop_banner_url: Optional[AnyHttpUrl]
	shop_url: Optional[AnyHttpUrl]
	etsy_owner_email: Optional[EmailStr]
	etsy_user_id: Optional[str]
	etsy_oauth_token: Optional[str]
	etsy_oauth_token_secret: Optional[str]
	# temp_oauth_verifier: Optional[str] = Field(alias="verifier")
	request_temporary_oauth_token: Optional[str]
	request_temporary_oauth_token_secret: Optional[str]
	verified: bool = Field(default=False)
	createdAt: datetime.datetime = Field(default=datetime.datetime.now())
	
	class Config:
		allow_population_by_field_name = True
		arbitrary_types_allowed = True
		json_encoders = {ObjectId: str}


class UpdateEtsyShopConnection(BaseModel):
	etsy_shop_name: Optional[str]
	etsy_shop_id: Optional[str]
	etsy_owner_email: Optional[EmailStr]
	etsy_user_id: Optional[str]
	etsy_oauth_token: Optional[str]
	etsy_oauth_token_secret: Optional[str]
	verified: Optional[bool]
# temp_oauth_verifier: Optional[str]