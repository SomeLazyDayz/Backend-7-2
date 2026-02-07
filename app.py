import os
import smtplib  # Thư viện gửi mail
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from datetime import datetime
from flask_cors import CORS
from dateutil.parser import parse

# Import geocoding MIỄN PHÍ (File geocoding_free.py phải nằm cùng thư mục)
from geocoding_free import geocode_address

# --- KHỞI TẠO VÀ CẤU HÌNH ---
app = Flask(__name__)
# Cấu hình CORS để cho phép Frontend (port 3000) gọi API
cors = CORS(app, resources={r"/*": {"origins": "http://localhost:3000"}}, supports_credentials=True)

app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///blood.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Cấu hình SQLite nâng cao để tránh lỗi "database is locked"
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'connect_args': {
        'timeout': 30,
        'check_same_thread': False
    },
    'pool_pre_ping': True,
    'pool_recycle': 3600,
}

db = SQLAlchemy(app)
migrate = Migrate(app, db)


# --- CẤU HÌNH EMAIL HỆ THỐNG ---
# Đã điền sẵn thông tin của bạn
SENDER_EMAIL = "minhtuandoanxxx@gmail.com"
APP_PASSWORD = "mavn ohfr xwtz cvgg"


# --- MODELS (CƠ SỞ DỮ LIỆU) ---
class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, default='')
    phone = db.Column(db.String(15), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(100), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='donor')
    address = db.Column(db.String(200), nullable=True)
    lat = db.Column(db.Float, nullable=True)
    lng = db.Column(db.Float, nullable=True)
    blood_type = db.Column(db.String(5), nullable=True)
    last_donation = db.Column(db.Date, nullable=True)

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'phone': self.phone,
            'email': self.email,
            'role': self.role,
            'address': self.address,
            'lat': self.lat,
            'lng': self.lng,
            'blood_type': self.blood_type,
            'last_donation': self.last_donation.isoformat() if self.last_donation else None
        }

class Hospital(db.Model):
    __tablename__ = 'hospitals'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    lat = db.Column(db.Float, nullable=False)
    lng = db.Column(db.Float, nullable=False)

    def to_dict(self):
         return {'id': self.id, 'name': self.name, 'lat': self.lat, 'lng': self.lng }


# --- CÁC API ROUTE CƠ BẢN ---

@app.route('/')
def index():
    return jsonify({'message': 'Blood Donation API is running!'})

@app.route('/users', methods=['GET'])
def get_users():
    users = User.query.all()
    return jsonify({'count': len(users), 'users': [user.to_dict() for user in users]})

@app.route('/hospitals', methods=['GET'])
def get_hospitals():
    hospitals = Hospital.query.all()
    return jsonify({'count': len(hospitals), 'hospitals': [h.to_dict() for h in hospitals]})


# --- ĐĂNG KÝ & ĐĂNG NHẬP ---

@app.route('/register_donor', methods=['POST'])
def register_donor():
    data = request.get_json()

    # Validate thông tin
    required_fields = ['fullName', 'email', 'phone', 'password', 'address', 'bloodType']
    if not all(field in data and data[field] for field in required_fields):
        return jsonify({'error': 'Thiếu thông tin bắt buộc hoặc thông tin rỗng'}), 400

    # Kiểm tra trùng lặp
    if User.query.filter((User.email == data['email']) | (User.phone == data['phone'])).first():
         return jsonify({'error': 'Email hoặc số điện thoại đã tồn tại'}), 409

    # Xử lý địa chỉ -> tọa độ (Geocoding)
    address = data['address']
    lat, lng = None, None
    try:
        coords = geocode_address(address)
        if coords:
            lat, lng = coords
            print(f"✅ Geocoding thành công: {lat}, {lng}")
        else:
            print(f"⚠️ Không tìm thấy tọa độ cho '{address}'")
    except Exception as e:
        print(f"❌ Lỗi geocoding: {e}")

    # Xử lý ngày hiến máu
    last_donation_date = None
    if data.get('lastDonationDate'):
        date_str = data['lastDonationDate']
        if date_str:
            try:
                last_donation_date = parse(date_str).date()
            except (ValueError, TypeError):
                 return jsonify({'error': 'Định dạng ngày không hợp lệ'}), 400

    # Tạo user mới
    new_user = User(
        name=data['fullName'],
        email=data['email'],
        phone=data['phone'],
        password=data['password'], 
        role='donor',
        address=address,
        lat=lat,
        lng=lng,
        blood_type=data['bloodType'],
        last_donation=last_donation_date
    )

    try:
        db.session.add(new_user)
        db.session.commit()
        user_dict = new_user.to_dict()
        
        msg = 'Đăng ký thành công'
        if lat is None:
             msg += ' (nhưng chưa xác định được tọa độ)'
        
        return jsonify({'message': msg, 'user': user_dict}), 201
        
    except Exception as e:
        db.session.rollback()
        print(f"Lỗi DB: {e}")
        return jsonify({'error': 'Lỗi máy chủ nội bộ'}), 500


@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    if not data or not data.get('email') or not data.get('password'):
        return jsonify({'error': 'Thiếu email hoặc mật khẩu'}), 400
    
    user = User.query.filter_by(email=data['email']).first()
    
    if user and user.password == data['password']:
        return jsonify({'message': 'Đăng nhập thành công', 'user': user.to_dict()}), 200
    else:
        # Trả về 401 để Frontend bắt lỗi hiển thị bảng đỏ
        return jsonify({'error': 'Email hoặc mật khẩu không chính xác'}), 401


# --- TÍNH NĂNG LỌC TÌNH NGUYỆN VIÊN (AI FILTER) ---

@app.route('/create_alert', methods=['POST'])
def create_alert():
    data = request.get_json()
    
    if not data.get('hospital_id') or not data.get('blood_type'):
        return jsonify({'error': 'Thiếu thông tin bệnh viện hoặc nhóm máu'}), 400
        
    hospital = Hospital.query.get(data['hospital_id'])
    if not hospital:
        return jsonify({'error': 'Không tìm thấy bệnh viện'}), 404
        
    blood_type_needed = data['blood_type']
    radius_km = data.get('radius_km', 10)
    
    # Lấy danh sách donor phù hợp sơ bộ (cùng nhóm máu, có tọa độ)
    suitable_users = User.query.filter(
        User.role == 'donor',
        User.lat.isnot(None),
        User.lng.isnot(None),
        User.blood_type == blood_type_needed
    ).all()
    
    try:
        # Gọi thuật toán lọc (file ai_filter.py)
        from ai_filter import filter_nearby_users
        results = filter_nearby_users(hospital, suitable_users, radius_km)
        
        # Lấy top 50
        top_50_users = results[:50]
        
        return jsonify({
            'hospital': hospital.to_dict(),
            'blood_type_needed': blood_type_needed,
            'total_matched': len(results),
            'top_50_users': [
                {
                    'user': r['user'].to_dict(), 
                    'distance_km': r['distance'], 
                    'ai_score': r['ai_score']
                }
                for r in top_50_users
            ]
        })
    except ImportError:
        return jsonify({'error': "Thiếu file ai_filter.py"}), 500
    except Exception as e:
        print(f"Lỗi AI Filter: {e}")
        return jsonify({'error': 'Lỗi xử lý lọc người dùng'}), 500


@app.route('/users/<int:user_id>', methods=['PUT', 'PATCH'])
def update_user_profile(user_id):
    user = User.query.get_or_404(user_id)
    data = request.get_json()
    allowed_fields = ['name', 'phone', 'address', 'blood_type', 'last_donation']
    
    geocoding_needed = False
    old_address = user.address
    
    for field in allowed_fields:
        if field in data:
            if field == 'last_donation':
                if data[field]:
                    try:
                        setattr(user, field, parse(data[field]).date())
                    except: pass
                else:
                     setattr(user, field, None)
            else:
                 setattr(user, field, data[field])
            
            if field == 'address' and data[field] != old_address:
                geocoding_needed = True

    if geocoding_needed and user.address:
        try:
            coords = geocode_address(user.address)
            if coords:
                user.lat, user.lng = coords
        except Exception: pass

    try:
        db.session.commit()
        return jsonify({'message': 'Cập nhật thành công', 'user': user.to_dict()}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': 'Lỗi cập nhật'}), 500


# --- GỬI EMAIL HTML CHO TÌNH NGUYỆN VIÊN ---

@app.route('/notify_donors', methods=['POST'])
def notify_donors():
    data = request.get_json()
    donor_ids = data.get('donor_ids')
    message_body = data.get('message')

    if not donor_ids or not message_body:
        return jsonify({'error': 'Thiếu ID người nhận hoặc nội dung'}), 400

    try:
        users_to_notify = User.query.filter(User.id.in_(donor_ids)).all()
        success_count = 0
        
        # Kết nối SMTP Gmail
        print("🔌 Đang kết nối Gmail...")
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(SENDER_EMAIL, APP_PASSWORD)
        print("✅ Kết nối thành công!")

        print(f"📧 Đang gửi email tới {len(users_to_notify)} người...")

        for user in users_to_notify:
            if user.email:
                try:
                    msg = MIMEMultipart()
                    msg['From'] = SENDER_EMAIL
                    msg['To'] = user.email
                    msg['Subject'] = f"🩸 KHẨN CẤP: CẦN MÁU NHÓM {user.blood_type} - GIỌT ẤM"

                    # Nội dung HTML đẹp
                    html_body = f"""
                    <!DOCTYPE html>
                    <html>
                    <head>
                        <style>
                            body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; background-color: #f4f4f4; }}
                            .email-container {{ max-width: 600px; margin: 20px auto; background-color: #ffffff; border-radius: 8px; overflow: hidden; }}
                            .header {{ background-color: #930511; color: #ffffff; padding: 20px; text-align: center; }}
                            .header h1 {{ margin: 0; }}
                            .content {{ padding: 25px; }}
                            .alert-box {{ background-color: #fbe4e6; border-left: 5px solid #930511; padding: 15px; margin: 20px 0; }}
                            .alert-title {{ color: #930511; font-weight: bold; margin-top: 0; }}
                            .btn-action {{ display: block; width: 200px; margin: 20px auto; padding: 12px; background-color: #930511; color: white !important; text-align: center; text-decoration: none; border-radius: 50px; font-weight: bold; }}
                            .footer {{ background-color: #f9f9f9; padding: 15px; text-align: center; font-size: 12px; color: #888; }}
                        </style>
                    </head>
                    <body>
                        <div class="email-container">
                            <div class="header">
                                <h1>🩸 GIỌT ẤM</h1>
                                <p>Kết nối yêu thương - Sẻ chia sự sống</p>
                            </div>
                            <div class="content">
                                <p>Xin chào <strong>{user.name}</strong>,</p>
                                <p>Hệ thống <strong>Giọt Ấm</strong> vừa nhận được thông báo khẩn cấp:</p>
                                
                                <div class="alert-box">
                                    <p class="alert-title">📢 THÔNG BÁO CẦN MÁU</p>
                                    <p>{message_body}</p>
                                </div>

                                <p>Sự giúp đỡ của bạn có thể cứu sống một mạng người. Hãy đến bệnh viện sớm nhất nếu có thể.</p>
                                <a href="#" class="btn-action">Tôi sẽ tham gia</a>
                                <p>Trân trọng,<br>Đội ngũ Giọt Ấm</p>
                            </div>
                            <div class="footer">
                                <p>Email tự động từ hệ thống Giọt Ấm.</p>
                            </div>
                        </div>
                    </body>
                    </html>
                    """
                    
                    msg.attach(MIMEText(html_body, 'html'))
                    server.send_message(msg)
                    print(f"✅ Đã gửi cho {user.name}")
                    success_count += 1
                except Exception as e:
                    print(f"⚠️ Lỗi gửi {user.name}: {e}")
        
        server.quit()
        return jsonify({'message': f'Đã gửi thành công {success_count} email.'}), 200

    except Exception as e:
        print(f"❌ Lỗi Server Mail: {e}")
        return jsonify({'error': 'Lỗi hệ thống gửi mail'}), 500


# --- XỬ LÝ FORM LIÊN HỆ (GỬI VỀ ADMIN) ---

@app.route('/contact_support', methods=['POST'])
def contact_support():
    data = request.get_json()
    name = data.get('name')
    email = data.get('email')
    phone = data.get('phone')
    message = data.get('message')

    if not all([name, email, phone, message]):
        return jsonify({'error': 'Vui lòng điền đầy đủ thông tin'}), 400

    # Email nhận thư (Gửi về chính Admin)
    RECEIVER_EMAIL = SENDER_EMAIL 

    try:
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(SENDER_EMAIL, APP_PASSWORD)

        msg = MIMEMultipart()
        msg['From'] = SENDER_EMAIL
        msg['To'] = RECEIVER_EMAIL
        msg['Subject'] = f"🔔 [LIÊN HỆ] Tin nhắn mới từ {name}"

        body = f"""
        Xin chào Admin Giọt Ấm,

        Bạn có một liên hệ mới từ website:
        ------------------------------------------------
        👤 Người gửi: {name}
        📧 Email: {email}
        📞 SĐT: {phone}
        ------------------------------------------------
        📝 Nội dung tin nhắn:
        {message}
        ------------------------------------------------
        """
        msg.attach(MIMEText(body, 'plain'))

        server.send_message(msg)
        server.quit()

        print(f"✅ Đã nhận liên hệ từ {name}")
        return jsonify({'message': 'Cảm ơn bạn! Chúng tôi đã nhận được tin nhắn.'}), 200

    except Exception as e:
        print(f"❌ Lỗi gửi mail liên hệ: {e}")
        return jsonify({'error': 'Lỗi hệ thống gửi mail'}), 500


# --- CHẠY APP ---
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True, port=5000)