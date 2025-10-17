import click
import os
from flask import Flask, render_template, request, redirect, url_for, jsonify, abort
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin, LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import datetime

# --- App and Database Configuration ---
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'a-default-secret-key-for-local-dev')

# Database Connection String for PythonAnywhere (MySQL)
db_username = os.environ.get('DB_USERNAME')
db_password = os.environ.get('DB_PASSWORD')
db_hostname = os.environ.get('DB_HOSTNAME')
db_name = os.environ.get('DB_NAME')

if all([db_username, db_password, db_hostname, db_name]):
    app.config['SQLALCHEMY_DATABASE_URI'] = (
        f"mysql+mysqlconnector://{db_username}:{db_password}@{db_hostname}/{db_name}"
    )
else:
    # Fallback for local development using SQLite
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///madira.db'

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# --- LOGIN MANAGER SETUP ---
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# --- Database Models (Tables) ---
class Store(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    location = db.Column(db.String(200))
    license_validity = db.Column(db.Date, nullable=False)
    users = db.relationship('User', backref='store', lazy=True)
    products = db.relationship('Product', backref='store', lazy=True)
    sales = db.relationship('Sale', backref='store', lazy=True)

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), nullable=False)
    store_id = db.Column(db.Integer, db.ForeignKey('store.id'), nullable=True)

    def set_password(self, password): self.password_hash = generate_password_hash(password)
    def check_password(self, password): return check_password_hash(self.password_hash, password)

class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    barcode = db.Column(db.String(100), nullable=True)
    name = db.Column(db.String(100), nullable=False)
    brand = db.Column(db.String(100))
    category = db.Column(db.String(50))
    size_ml = db.Column(db.Integer, nullable=False)
    price = db.Column(db.Float, nullable=False)
    stock_quantity = db.Column(db.Integer, nullable=False, default=0)
    store_id = db.Column(db.Integer, db.ForeignKey('store.id'), nullable=False)
    def to_dict(self): return {'id': self.id, 'barcode': self.barcode, 'name': self.name, 'brand': self.brand,'category': self.category, 'size_ml': self.size_ml, 'price': self.price, 'stock_quantity': self.stock_quantity}

class Sale(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    total_amount = db.Column(db.Float, nullable=False)
    sale_date = db.Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow)
    store_id = db.Column(db.Integer, db.ForeignKey('store.id'), nullable=False)
    items = db.relationship('SaleItem', backref='sale', lazy=True, cascade="all, delete-orphan")

class SaleItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sale_id = db.Column(db.Integer, db.ForeignKey('sale.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    price_at_sale = db.Column(db.Float, nullable=False)
    product = db.relationship('Product')

# --- Authentication Routes ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        if current_user.role == 'superadmin': return redirect(url_for('superadmin_dashboard'))
        if current_user.role == 'admin': return redirect(url_for('sales'))
        else: return redirect(url_for('billing'))

    if request.method == 'POST':
        user = User.query.filter_by(username=request.form['username']).first()
        if user and user.check_password(request.form['password']):
            login_user(user)
            if user.role == 'superadmin': return redirect(url_for('superadmin_dashboard'))
            if user.role == 'admin': return redirect(url_for('sales'))
            else: return redirect(url_for('billing'))
        return render_template('login.html', error="Invalid username or password.")
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

# --- Superadmin Routes ---
@app.route('/superadmin')
@login_required
def superadmin_dashboard():
    if current_user.role != 'superadmin': return abort(403)
    all_stores = Store.query.order_by(Store.license_validity).all()
    today = datetime.date.today()
    return render_template('superadmin_dashboard.html', stores=all_stores, today=today)

@app.route('/superadmin/update_license/<int:store_id>', methods=['POST'])
@login_required
def update_license(store_id):
    if current_user.role != 'superadmin':
        return abort(403)
    
    store = Store.query.get_or_404(store_id)
    new_date_str = request.form.get('new_validity')
    
    if new_date_str:
        try:
            new_date = datetime.datetime.strptime(new_date_str, '%Y-%m-%d').date()
            store.license_validity = new_date
            db.session.commit()
        except ValueError:
            pass
    
    return redirect(url_for('superadmin_dashboard'))

# --- Store-Specific App Routes ---
@app.route('/')
@app.route('/dashboard', methods=['GET', 'POST'])
@login_required
def dashboard():
    if current_user.role == 'superadmin': return redirect(url_for('superadmin_dashboard'))
    
    if request.method == 'POST':
        if current_user.role != 'store': return abort(403)
        new_product = Product(name=request.form['name'], brand=request.form['brand'],
                              category=request.form['category'], size_ml=int(request.form['size_ml']),
                              price=float(request.form['price']), barcode=request.form['barcode'],
                              stock_quantity=int(request.form['stock_quantity']),
                              store_id=current_user.store_id)
        db.session.add(new_product)
        db.session.commit()
        return redirect(url_for('dashboard'))

    products = Product.query.filter_by(store_id=current_user.store_id).order_by(Product.name).all()
    return render_template('dashboard.html', products=products)

@app.route('/update_stock', methods=['POST'])
@login_required
def update_stock():
    if current_user.role != 'store': return abort(403)
    product_id = request.form['product_id']
    quantity_to_add = int(request.form['add_stock'])
    product = Product.query.filter_by(id=product_id, store_id=current_user.store_id).first_or_404()
    if quantity_to_add > 0:
        product.stock_quantity += quantity_to_add
        db.session.commit()
    return redirect(url_for('dashboard'))

@app.route('/billing')
@login_required
def billing():
    if current_user.role != 'store': return abort(403)
    return render_template('billing.html')

@app.route('/sales')
@login_required
def sales():
    if current_user.role != 'admin': return abort(403)
    all_sales = Sale.query.filter_by(store_id=current_user.store_id).order_by(Sale.sale_date.desc()).all()
    return render_template('sales.html', sales=all_sales, store_name=current_user.store.name)

# --- API Endpoints ---
@app.route('/api/products')
@login_required
def get_products():
    if current_user.role not in ['store', 'admin']: return abort(403)
    products = Product.query.filter(Product.store_id==current_user.store_id, Product.stock_quantity > 0).all()
    return jsonify([p.to_dict() for p in products])

@app.route('/api/process_bill', methods=['POST'])
@login_required
def process_bill():
    if current_user.role != 'store': return abort(403)
    data = request.get_json()
    bill_items = data.get('items', [])
    if not bill_items: return jsonify({'success': False, 'error': 'Empty bill'}), 400
    
    try:
        total_amount = 0
        new_sale = Sale(total_amount=0, store_id=current_user.store_id)
        db.session.add(new_sale)

        for item in bill_items:
            product = Product.query.filter_by(id=item['id'], store_id=current_user.store_id).first()
            if not product or product.stock_quantity < item['quantity']:
                db.session.rollback()
                return jsonify({'success': False, 'error': f"Not enough stock for {product.name if product else 'ID '+str(item['id'])}"}), 400
            
            product.stock_quantity -= item['quantity']
            sale_item = SaleItem(sale=new_sale, product_id=product.id,
                                 quantity=item['quantity'], price_at_sale=product.price)
            total_amount += product.price * item['quantity']
            db.session.add(sale_item)
        
        new_sale.total_amount = round(total_amount, 2)
        db.session.commit()
        return jsonify({'success': True, 'sale_id': new_sale.id})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

# --- CLI Commands ---
@app.cli.command("init-db")
def init_db_command():
    """Clears the existing data and creates new tables."""
    db.create_all()
    print("✅ Initialized the database.")

@app.cli.command("create-store")
@click.argument("name")
@click.argument("location")
@click.argument("validity")
def create_store(name, location, validity):
    """Creates a new store. Validity format: YYYY-MM-DD"""
    try:
        validity_date = datetime.datetime.strptime(validity, '%Y-%m-%d').date()
        new_store = Store(name=name, location=location, license_validity=validity_date)
        db.session.add(new_store)
        db.session.commit()
        print(f"✅ Store '{name}' created with ID: {new_store.id}")
    except Exception as e:
        print(f"❌ Error creating store: {e}")

@app.cli.command("create-user")
@click.argument("username")
@click.argument("password")
@click.argument("role")
@click.argument("store_id", default=0)
def create_user(username, password, role, store_id):
    """Creates a user. For admin/store, provide a store_id."""
    if role not in ['superadmin', 'admin', 'store']:
        return print("❌ Error: Role must be 'superadmin', 'admin', or 'store'.")
    
    user_store_id = int(store_id) if store_id != 0 else None
    if role in ['admin', 'store'] and not user_store_id:
        return print("❌ Error: A store_id must be provided for admin and store roles.")
    if role == 'superadmin' and user_store_id:
        return print("❌ Error: Superadmin cannot be assigned to a store.")
        
    new_user = User(username=username, role=role, store_id=user_store_id)
    new_user.set_password(password)
    db.session.add(new_user)
    db.session.commit()
    print(f"✅ User '{username}' with role '{role}' created successfully.")

if __name__ == '__main__':
    app.run(debug=True)
