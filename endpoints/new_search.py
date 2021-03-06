import datetime
from typing import List, Optional
from starlette import status
from schemas import UserData
from fastapi import APIRouter, Depends, HTTPException
from oauth2 import is_authenticated
from database import MongoDB, ReceiptNoteStatus
from pydantic import BaseModel
import pprint
from config import DEFAULT_SEARCH_PAGE, DEFAULT_SEARCH_LIMIT

mongodb = MongoDB()

router = APIRouter(
    prefix="/new_search",
    tags=["new search"],
    responses={404: {"description": "Not found"}},
)


class NewSearchBody(BaseModel):
	from_date: Optional[datetime.datetime] = None
	to_date: Optional[datetime.datetime] = None
	query: Optional[str] = None
	receipt_status: Optional[ReceiptNoteStatus] = None
	shop_name: Optional[str] = None
	projection: Optional[List[str]] = None,
	item_type: Optional[str] = None
	


@router.post('/')
async def new_search(
	search_body: NewSearchBody,
	page: int = DEFAULT_SEARCH_PAGE,
	limit: int = DEFAULT_SEARCH_LIMIT,
	user: UserData = Depends(is_authenticated) 
):
	if limit > DEFAULT_SEARCH_LIMIT:
		limit = DEFAULT_SEARCH_LIMIT

	# search_body = search_body.dict()
	# search_body = {k: search_body[k] for k in search_body.keys() if search_body[k] is not None}
	pprint.pprint(search_body)
	# pipeline = []
	collation = {}
	match = {}
	project = {
		"_id": False,
		"Note": True
	}
	if search_body.item_type is not None:
		match['Listings.title'] = search_body.item_type
	if search_body.receipt_status is not None:
		match['Note.status'] = search_body.receipt_status
	if search_body.shop_name is not None:
		match['shop_name'] = search_body.shop_name
	if search_body.from_date is not None and search_body.to_date is not None:
		match["max_due_date"] = {
			"$lte": search_body.to_date,
			"$gte": search_body.from_date
		}
	elif search_body.from_date is not None and search_body.to_date is None:
		match["max_due_date"] = {
			"$lte": search_body.from_date,
			"$gte": search_body.from_date
		}
	elif search_body.from_date is None and search_body.to_date is not None:
		match["max_due_date"] = {
			"$lte": search_body.to_date,
			"$gte": search_body.to_date
		}
	is_int: bool = False
	if search_body.query is not None:
		try:
			int(search_body.query)
		except ValueError:
			is_int = False
		else:
			search_body.query = int(search_body.query)
			is_int = True
		if is_int:
			match["receipt_id"] = search_body.query
		else:
			match["name"] = search_body.query
			collation["locale"] = "en"
			collation["strength"] = 1
	if search_body.projection is not None and len(search_body.projection) > 0:
		for p in search_body.projection:
			if p == "_id":
				continue
			project[p] = True
	print(match)
	print(project)

	mongodb_search_result = await mongodb.db['Receipts'].aggregate([
		{
			'$lookup': {
				'from': 'Notes', 
				'localField': 'receipt_id', 
				'foreignField': 'receipt_id', 
				'as': 'Note'
			}
		}, {
			'$match': {**match}
		}, {
			"$sort": {
				'max_due_date': 1,
			}
		}, {
			'$unwind': {
				'path': '$Note',
				'preserveNullAndEmptyArrays': True
			}
		},{
			"$project": {**project}
		}, {
			"$unset": ['Note._id']
		}, {
			"$facet": {
				'pagination': [
					{ '$count': 'total' },
					{'$addFields': { 'page': page } }
				],
				'data': [
					{ '$skip': (page - 1) * limit },
					{ '$limit': limit }
				]
			}
		}
	]).to_list(length=limit)
	# print()
	# search_result = []
	# async for receipt in mongodb_search_result:
	# 	search_result.append(receipt)
	return mongodb_search_result


