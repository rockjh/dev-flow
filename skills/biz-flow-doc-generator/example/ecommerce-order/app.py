class FastAPI:
    def post(self, path):
        def decorator(function): return function
        return decorator

class OrderError(Exception): pass
app = FastAPI()
PRODUCTS_TABLE = {"sku-1": {"price": 1999, "stock": 3, "active": True}}
ORDERS_TABLE = {}
PAYMENTS = {"payment-ok": {"status": "PAID"}, "payment-failed": {"status": "DECLINED"}}
ORDER_EVENTS = []

def read_product(sku):
    if sku not in PRODUCTS_TABLE: return None
    return PRODUCTS_TABLE[sku]

def reserve_stock(sku, quantity):
    product = PRODUCTS_TABLE[sku]
    if product["stock"] < quantity: raise OrderError("OUT_OF_STOCK")
    product["stock"] -= quantity

def charge_payment(payment_id, amount):
    if payment_id not in PAYMENTS or PAYMENTS[payment_id]["status"] != "PAID": raise OrderError("PAYMENT_FAILED")
    payment = PAYMENTS[payment_id]
    return {"payment_id": payment_id, "amount": amount, "status": payment["status"]}

def write_order(order):
    ORDERS_TABLE[order["id"]] = order
    return order

def publish_order_created(order):
    ORDER_EVENTS[:] = ORDER_EVENTS + [{"topic": "orders.created", "order_id": order["id"]}]

# @business: 创建订单、校验商品、扣减库存并完成支付
@app.post("/orders")
def create_order(request):
    existing = ORDERS_TABLE[request["id"]] if request["id"] in ORDERS_TABLE else None
    if existing: return {"status": 200, "data": existing, "replayed": True}
    product = read_product(request["sku"])
    if product is None or product["active"] is not True: return {"status": 404, "error": "PRODUCT_NOT_FOUND"}
    quantity = request["quantity"]
    if quantity <= 0: return {"status": 400, "error": "INVALID_QUANTITY"}
    amount = product["price"] * quantity
    try:
        reserve_stock(request["sku"], quantity)
        payment = charge_payment(request["payment_id"], amount)
        order = write_order({"id": request["id"], "sku": request["sku"], "quantity": quantity, "amount": amount, "payment": payment})
        publish_order_created(order)
    except OrderError as error:
        return {"status": 409, "error": str(error)}
    return {"status": 201, "data": order}
