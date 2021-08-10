import pprint
# from pydantic.fields import T
from termcolor import colored

from datetime import datetime
from typing import List, Optional

from pymongo import errors
from helpers import calculate_max_min_due_date

from bson import ObjectId

from AsyncEtsyApi import AsyncEtsy, Method, EtsyUrl
from MyLogger import Logger
logging = Logger().logging

from database import MongoDB, MyRedis, ReceiptNoteStatus
# import pytz

class MyEtsyShopManager:
	
	def __init__(self, shop_name):
		self.shop_name = shop_name
	
	async def insert_receipt(self, receipt: dict, db):
		receipt.update({"shop_name": self.shop_name})
		receipt_insert_result = await db["Receipts"].insert_one(receipt)
		return receipt_insert_result.inserted_id
	

	async def insert_notes(self, inserted_ids):
		if len(inserted_ids) == 0:
			return
		mongodb = MongoDB()
		db = mongodb.db
		notes = []
		for receipt_mongodb_id in inserted_ids:
			receipt = await db["Receipts"].find_one({'_id': receipt_mongodb_id})
			note = {
				'receipt_id':receipt["receipt_id"], 
				'created_at': datetime.now(), 
				'status': ReceiptNoteStatus.uncompleted
			}
			notes.append(note)
			pprint.pprint(note)
		try:
			insert_all_notes_result = await db['Notes'].insert_many(notes)
		except errors.BulkWriteError as e:
			panic_list = list(filter(lambda x: x['code'] != 11000, e.details['writeErrors']))
			if len(panic_list) > 0:
				logging.info(f"these are not duplicate errors {panic_list}")
			else:
				for writeError in e.details['writeErrors']:
					logging.info(f"{writeError}")

	async def insert_receipts(self, receipts: List[dict], db):
		if len(receipts) <= 0:
			return []
		for r in receipts:
			r["shop_name"] = self.shop_name
		try:
			insert_all_receipts_result = await db["Receipts"].insert_many(receipts)
		except errors.BulkWriteError as e:
			# logging.error(f"Articles bulk write insertion error {e}")
			panic_list = list(filter(lambda x: x['code'] != 11000, e.details['writeErrors']))
			if len(panic_list) > 0:
				logging.info(f"these are not duplicate errors {panic_list}")
			else:
				for writeError in e.details['writeErrors']:
					logging.info(f"{writeError}")
		else:
			await self.insert_notes(insert_all_receipts_result.inserted_ids)
		finally:
			return [(str(mongodb_id), receipt["receipt_id"]) for mongodb_id, receipt in zip(insert_all_receipts_result.inserted_ids, receipts)]
		# return insert_all_receipts_result.inserted_ids
	
	async def update_receipt(self, mongodb_id: str, receipt_id: str, transactions: List[dict], db):
		if type(mongodb_id) is not ObjectId:
			mongodb_id = ObjectId(mongodb_id)
		update_receipt_result = await db["Receipts"].update_one(
			{"_id": mongodb_id, "receipt_id": receipt_id},
			{
				"$set": {
					"transactions": transactions
				}
			}
		)
	
	@staticmethod
	async def check_unpaids(etsy_connection_id, asyncEtsyApi, params, r):
		logging.info(f"Checking unpaid receipts {etsy_connection_id}")
		my_params = dict(params)
		my_params.pop("min_created", None)
		receipts_not_paid = []
		receipts_to_be_inserted = []
		unpaid_from_redis = r.get(f"{etsy_connection_id}:unpaid_receipts")
		if unpaid_from_redis is not None and len(unpaid_from_redis) > 0:
			
			unpaid_responses = await AsyncEtsy.asyncLoop(
				f=asyncEtsyApi.getAllPages,
				method=Method.get,
				url=EtsyUrl.getShop_Receipt2(unpaid_from_redis),
				params=my_params
			)
			logging.info(f"{len(unpaid_responses)} pages of fetched receipts found.")
			
			for res in unpaid_responses:
				if res.status_code != 200:
					continue
				res_json = res.json()
				results: List[dict] = res_json["results"]
				for receipt in results:
					logging.info(receipt['receipt_id'])
					was_paid: bool = receipt["was_paid"]
					logging.info(f"was_paid: {was_paid}")
					# logging.info(f"{receipt['receipt_id']} -> Transactions[0]: {f'\n\t' + str(receipt['Transactions'][0]['receipt_id'])} {f'\n\t' + str(receipt['Transactions'][0]['paid_tsz'])}")
					paid_tzs: Optional[int] = receipt["Transactions"][0]["paid_tsz"]
					if not was_paid or paid_tzs is None:
						logging.info(f"{receipt['receipt_id']} : was_paid={was_paid} : paid_tzs={paid_tzs}. Probably processing payment in the Etsy side.")
						# pop_list.append(i)
						receipts_not_paid.append(receipt["receipt_id"])
						continue
					calculate_max_min_due_date(receipt)
					receipts_to_be_inserted.append(receipt)
				# for pop_index in pop_list:
				# 	results.pop(pop_index)
				# receipts_to_be_inserted = numpy.concatenate((receipts_to_be_inserted, results))
		logging.info(f"{asyncEtsyApi.shop_id} Receipts to be inserted -> {' , '.join(str(receipt['receipt_id']) for receipt in receipts_to_be_inserted)}")
		logging.info(f"{asyncEtsyApi.shop_id} Not yet finished payment process Receipts -> {receipts_not_paid}")
		return receipts_not_paid, receipts_to_be_inserted
	
	@staticmethod
	async def check_for_new_orders(asyncEtsyApi, params):
		logging.info(f"Checking for new orders {asyncEtsyApi.shop_id}")
		receipts_not_paid = []
		receipts_to_be_inserted = []
		receipt_responses = await AsyncEtsy.asyncLoop(
			f=asyncEtsyApi.getAllPages,
			method=Method.get,
			url=EtsyUrl.findAllShopReceipts(asyncEtsyApi.shop_id),
			params=params
		)
		
		for res in receipt_responses:
			if res.status_code != 200:
				continue
			res_json = res.json()
			results: List[dict] = res_json["results"]
			for receipt in results:
				logging.info(receipt['receipt_id'])
				was_paid: bool = receipt["was_paid"]
				logging.info(f"was_paid: {was_paid}")
				paid_tzs: Optional[int] = receipt["Transactions"][0]["paid_tsz"]
				# logging.info(f"{receipt['receipt_id']} -> Transactions[0]: {receipt['Transactions'][0]}")
				if not was_paid or paid_tzs is None:
					logging.info(colored(f"{receipt['receipt_id']} : was_paid={was_paid} : paid_tzs={paid_tzs}. Probably processing payment in the Etsy side.", 'magenta', attrs=['underline', 'bold']))
					# pop_list.append(i)
					receipts_not_paid.append(receipt["receipt_id"])
					continue
				calculate_max_min_due_date(receipt)
				receipts_to_be_inserted.append(receipt)
			# for pop_index in pop_list:
			# 	results.pop(pop_index)
			# receipts_to_be_inserted = numpy.concatenate((receipts_to_be_inserted, results))
		# logging.info(receipts_not_paid)
		# logging.info(receipts_to_be_inserted)
		logging.info(f"{asyncEtsyApi.shop_id} Receipts to be inserted -> {' , '.join(str(receipt['receipt_id']) for receipt in receipts_to_be_inserted)}")
		logging.info(f"{asyncEtsyApi.shop_id} Not yet finished payment process Receipts -> {receipts_not_paid}")
		return receipts_not_paid, receipts_to_be_inserted
	
	# @staticmethod
	# async def syncShop(etsy_connection_id: str):
	# 	is_successfull = False
	# 	db = MongoDB().db
	# 	r = MyRedis().r
	# 	try:
	# 		is_running = r.get(f"{etsy_connection_id}:is_running")
	# 		logging.info(f"is_running: {is_running}")
	# 		if is_running == "True":
	# 			return {
	# 				"background-task": "already running"
	# 			}
	# 		else:
	# 			r.set(f"{etsy_connection_id}:is_running", "True")
	# 		last_updated = r.get(f"{etsy_connection_id}:last_updated")
	# 		params = {
	# 			"includes": "Transactions/MainImage,Listings/ShippingTemplate"
	# 		}
	# 		if last_updated is not None:
	# 			last_updated = int(last_updated)
	# 			logging.info("last_updated is not None, setting min_created")
	# 			params["min_created"] = last_updated
	# 		current_time = int(datetime.now().timestamp())
	# 		params["max_created"] = current_time
	# 		if last_updated is not None:
	# 			logging.info(f"From = {datetime.fromtimestamp(last_updated)}\nTo = {datetime.fromtimestamp(current_time)}")
	# 		else:
	# 			logging.info(f"From = -\nTo = {datetime.fromtimestamp(current_time)}")
			
	# 		asyncEtsyApi = await AsyncEtsy.getAsyncEtsyApi(etsy_connection_id, db)
	# 		etsyShopManager = EtsyShopManager(asyncEtsyApi.shop_id)
			
	# 		receipts_not_paid, receipts_to_be_inserted = await EtsyShopManager.check_unpaids(etsy_connection_id, asyncEtsyApi, params, r)
	# 		unpaid_receipts, r_to_be_inserted = await EtsyShopManager.check_for_new_orders(asyncEtsyApi, params)
	# 		receipts_not_paid = receipts_not_paid + unpaid_receipts
	# 		receipts_not_paid = set(receipts_not_paid)
	# 		receipts_not_paid = list(receipts_not_paid)
	# 		logging.info(f"{asyncEtsyApi.shop_id} Final Merged not yet finished payment processed Receipts -> {receipts_not_paid}")
	# 		r.set(f"{etsy_connection_id}:unpaid_receipts", ','.join(str(not_paid_receipt) for not_paid_receipt in receipts_not_paid))
	# 		receipts_to_be_inserted = receipts_to_be_inserted + r_to_be_inserted
	# 		logging.info(f"{asyncEtsyApi.shop_id} Final Receipts to be inserted into MongoDB -> {[receipt['receipt_id'] for receipt in receipts_to_be_inserted]}")
	# 		mongodb_result = await etsyShopManager.insert_receipts(receipts_to_be_inserted, db)
	# 		if len(mongodb_result) == len(receipts_to_be_inserted):
	# 			logging.info("successfully inserted all receipts")
	# 			logging.info("setting last_updated")
	# 			r.set(f"{etsy_connection_id}:last_updated", current_time)
	# 	except Exception as e:
	# 		logging.exception(e)
	# 	else:
	# 		is_successfull = True
	# 	finally:
	# 		logging.info(f".---'| {asyncEtsyApi.shop_id} {'was Successful' if is_successfull else 'Failed'} |'---.")
	# 		r.set(f"{etsy_connection_id}:is_running", "False")

async def syncShop(etsy_connection_id: str):
	logging.info(colored(f"Sync Etsy Shop receipts process started for etsy_shop_connection: {etsy_connection_id}", 'blue', attrs=['reverse', 'blink']))
	is_successfull = False
	db = MongoDB().db
	r = MyRedis().r
	try:
		is_running = r.get(f"{etsy_connection_id}:is_running")
		logging.info(f"is_running: {is_running}")
		if is_running == "True":
			logging.info(colored(f"{etsy_connection_id} is already running. Exisiting syncShop function.", 'yellow', 'on_grey', attrs=['blink']))
			return {
				"background-task": "already running"
			}
		else:
			r.set(f"{etsy_connection_id}:is_running", "True")
		last_updated = r.get(f"{etsy_connection_id}:last_updated")
		params = {
			"includes": "Transactions/MainImage,Listings/ShippingTemplate"
		}
		if last_updated is not None:
			last_updated = int(last_updated)
			logging.info("last_updated is not None, setting min_created")
			params["min_created"] = last_updated
		current_time = int(datetime.now().timestamp())
		params["max_created"] = current_time
		if last_updated is not None:
			logging.info(f"From = {datetime.fromtimestamp(last_updated)}")
			logging.info(f"To = {datetime.fromtimestamp(current_time)}")
		else:
			logging.info(f"From = -")
			logging.info(f"To = {datetime.fromtimestamp(current_time)}")
			
		asyncEtsyApi = await AsyncEtsy.getAsyncEtsyApi(etsy_connection_id, db)
		etsyShopManager = MyEtsyShopManager(asyncEtsyApi.shop_id)
			
		receipts_not_paid, receipts_to_be_inserted = await MyEtsyShopManager.check_unpaids(etsy_connection_id, asyncEtsyApi, params, r)
		unpaid_receipts, r_to_be_inserted = await MyEtsyShopManager.check_for_new_orders(asyncEtsyApi, params)
		receipts_not_paid = receipts_not_paid + unpaid_receipts
		receipts_not_paid = set(receipts_not_paid)
		receipts_not_paid = list(receipts_not_paid)
		logging.info(f"{asyncEtsyApi.shop_id} FINAL Receipts that paid_tsz was not found -> {colored(receipts_not_paid, attrs=['bold', 'underline'])}")
		r.set(f"{etsy_connection_id}:unpaid_receipts", ','.join(str(not_paid_receipt) for not_paid_receipt in receipts_not_paid))
		receipts_to_be_inserted = receipts_to_be_inserted + r_to_be_inserted
		logging.info(f"{asyncEtsyApi.shop_id} FINAL Receipts to be inserted into MongoDB -> {colored(' , '.join(str(receipt['receipt_id']) for receipt in receipts_to_be_inserted), attrs=['bold', 'underline'])}")
		mongodb_result = await etsyShopManager.insert_receipts(receipts_to_be_inserted, db)
		if len(mongodb_result) == len(receipts_to_be_inserted):
			logging.info(colored("successfully inserted all receipts", 'green', 'on_grey', attrs=['blink']))
			logging.info("setting last_updated")
			r.set(f"{etsy_connection_id}:last_updated", current_time)
	except Exception as e:
		logging.exception(e)
	else:
		is_successfull = True
	finally:
		r.set(f"{etsy_connection_id}:is_running", "False")
		try:
			logging.info(f".---'| {colored(asyncEtsyApi.shop_id, 'blue', 'on_grey', attrs=['bold', 'underline'])} {colored('was Successful', 'green', 'on_white', attrs=['reverse', 'blink', 'bold']) if is_successfull else colored('Failed', 'red', 'on_white', attrs=['reverse', 'blink', 'bold'])} |'---.")
		except UnboundLocalError:
			logging.info(f".---'| {colored(etsy_connection_id, 'blue', 'on_grey', attrs=['bold', 'underline'])} {colored('was Successful', 'green', 'on_white', attrs=['reverse', 'blink', 'bold']) if is_successfull else colored('Failed', 'red', 'on_white', attrs=['reverse', 'blink', 'bold'])} |'---.")
		