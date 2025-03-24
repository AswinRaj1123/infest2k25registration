from fastapi import FastAPI, HTTPException,Request
from pydantic import BaseModel
import qrcode
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from pymongo import MongoClient
import random
import os
from fastapi.responses import Response
from datetime import datetime
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
import logging
import uvicorn
from fastapi.responses import JSONResponse, RedirectResponse

load_dotenv()
os.makedirs("qrcodes", exist_ok=True)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins (Change to specific origins for security)
    allow_credentials=True,
    allow_methods=["*"],  # Allow all HTTP methods
    allow_headers=["*"],  # Allow all headers
)

# MongoDB Connection
MONGO_URI = (os.getenv("MONGO_URI"))
client = MongoClient(MONGO_URI)
db = client["infest_db"]
collection = db["registrations"]

# Email Configuration
EMAIL_USER = (os.getenv("EMAIL_USER"))
EMAIL_PASS = (os.getenv("EMAIL_PASS"))

# Pydantic Model for Validation
class RegistrationData(BaseModel):#
    name: str
    email: str
    phone: str
    whatsapp: str
    college: str
    year: str
    department: str
    events: list
    payment_mode: str
    project_link: str = None
    payment_id: str = None
    payment_status: str = "pending"

#class OrderRequest(BaseModel):
  #  amount: int

#class PaymentVerification(BaseModel):
  #  razorpay_order_id: str
  #  razorpay_payment_id: str
   # razorpay_signature: str
   # registration_data: dict

# Function to Generate Ticket ID
def generate_ticket_id():
    return f"INF25-{random.randint(1000, 9999)}"

# Function to Generate QR Code
def generate_qr(ticket_id):
    qr = qrcode.make(ticket_id)
    qr_path = f"qrcodes/{ticket_id}.png"
    os.makedirs(os.path.dirname(qr_path), exist_ok=True)
    qr.save(qr_path)
    return qr_path

# Function to Send Confirmation Email
def send_email(user_email, ticket_id, qr_path, user_data):
    msg = MIMEMultipart()
    msg["From"] = EMAIL_USER
    msg["To"] = user_email
    msg["Subject"] = "INFEST 2K25 - Registration Confirmation"

 # Determine payment status
    payment_status = "Paid" if user_data.get('payment_status') == "paid" else "Payment Pending"
    payment_info = "Payment completed successfully" if payment_status == "Paid" else "Please complete your payment at the venue"

    body = f"""
    <h2>Thank you for registering for INFEST 2K25!</h2>
    <p>Your ticket ID: <b>{ticket_id}</b></p>
    <p>Full Name: {user_data['name']}</p>
    <p>Email: {user_data['email']}</p>
    <p>Phone: {user_data['phone']}</p>
    <p>WhatsApp: {user_data['whatsapp']}</p>
    <p>College: {user_data['college']}</p>
    <p>Year: {user_data['year']}</p>
    <p>Department: {user_data['department']}</p>
    <p>Events: {', '.join(user_data['events'])}</p>
    <p>Payment Mode: {user_data['payment_mode']}</p>
    <p>Show the attached QR code at the event check-in.</p>
    """
    msg.attach(MIMEText(body, "html"))

    with open(qr_path, "rb") as f:
        img = MIMEImage(f.read(), name=f"{ticket_id}.png")
        msg.attach(img)

    try:
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(EMAIL_USER, EMAIL_PASS)
        server.sendmail(EMAIL_USER, user_email, msg.as_string())
        server.quit()
        return True
    except Exception as e:
        print("Email Error:", e)
        return False

@app.get("/")
async def root():
    return {"message": "Server is running"}
    

@app.post("/webhook")
async def razorpay_webhook(request: Request):
    payload = await request.json()
    print("Webhook Data:", payload)

    if payload.get('event') == "payment.captured":
        payment_id = payload["payload"]["payment"]["entity"]["id"]
        amount = payload["payload"]["payment"]["entity"]["amount"] / 100  # Convert paise to INR

        try:
            # Find the registration with this payment_id and update payment status
            result = collection.update_one(
                {"payment_id": payment_id},
                {"$set": {"payment_status": "paid"}}
            )
            
            if result.modified_count > 0:
                logger.info(f"✅ Payment Successful: ₹{amount} - Payment ID: {payment_id} - Database updated")
                # Fetch the ticket ID from the database
                registration = collection.find_one({"payment_id": payment_id})
                ticket_id = registration["ticket_id"]
                # Redirect to the tickets page with the ticket ID
                return RedirectResponse(url=f"/ticket.html?ticketId={ticket_id}")
            else:
                logger.warning(f"⚠ Payment received but no matching registration found: {payment_id}")
                return {"status": "warning", "message": "Payment recorded but no matching registration found"}
        
        except Exception as e:
            logger.error(f"❌ Database error while updating payment: {str(e)}")
            return JSONResponse(
                status_code=500,
                content={"status": "error", "message": f"Database error: {str(e)}"}
            )
    else:
        return {"status": "error", "message": "Invalid event type"}



@app.post("/register")
async def register_user(data: RegistrationData):
    
    # Generate a unique ticket ID
        # Generate ticket ID
    ticket_id = generate_ticket_id()
    
     # Generate QR Code
    qr_path = generate_qr(ticket_id)
    
     # Update user data
    user_data = data.dict()
    user_data["ticket_id"] = ticket_id
    user_data["payment_status"] = user_data.get('payment_status')
    user_data["registration_time"] = datetime.now().isoformat()
    
    try:
         # Save to database
         collection.insert_one(user_data)
    except Exception as e:
         raise HTTPException(status_code=500, detail=f"Database Error: {str(e)}")
    
     # Send confirmation email
    email_sent = send_email(data.email, ticket_id, qr_path, user_data)
    
    return {
         "status": "success", 
         "ticket_id": ticket_id, 
         "qr_code": qr_path, 
         "email_sent": email_sent,
         "payment_status": user_data.get('payment_status')
     }

@app.get("/health")
async def health_check():
    return Response(status_code=200)
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
    
# @app.get("/api/ticket/{ticket_id}")
# async def get_ticket_details(ticket_id: str):
#     registration = collection.find_one({"ticket_id": ticket_id})
#     if registration:
#         return {
#             "ticket_id": registration["ticket_id"],
#             "name": registration["name"],
#             "email": registration["email"],
#             "events": registration["events"],
#             "payment_status": registration["payment_status"],
#             "qr_code": registration["qr_code"]
#         }
#     else:
#         raise HTTPException(status_code=404, detail="Ticket not found")
