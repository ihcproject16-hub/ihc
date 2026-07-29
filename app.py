# =====================================================================
#  MULTI‑VENDOR E‑COMMERCE PLATFORM – All‑in‑One (Flask)
#  Features: Cart, Reviews, Pagination, Admin, Payments, Emails, Tests
#  Auto‑schema upgrade included – works with SQLite & PostgreSQL
#  Run locally: python app.py
#  Deploy on Render: set DATABASE_URL, SECRET_KEY, etc.
# =====================================================================

import os
import re
import unittest
from datetime import datetime
from flask import Flask, render_template_string, request, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_mail import Mail, Message
from flask_wtf import FlaskForm, CSRFProtect
from wtforms import StringField, TextAreaField, FloatField, IntegerField, SelectField, PasswordField, SubmitField
from wtforms.validators import DataRequired, Length, NumberRange, ValidationError
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import text

# ---------- CONFIG ----------
class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL', 'sqlite:///ecommerce.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    MAIL_SERVER = os.environ.get('MAIL_SERVER', 'smtp.gmail.com')
    MAIL_PORT = int(os.environ.get('MAIL_PORT', 587))
    MAIL_USE_TLS = os.environ.get('MAIL_USE_TLS', 'true').lower() == 'true'
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME')
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD')
    MAIL_DEFAULT_SENDER = os.environ.get('MAIL_DEFAULT_SENDER', 'noreply@marketplace.com')
    ITEMS_PER_PAGE = 12
    ADMIN_EMAIL = 'admin@example.com'
    ADMIN_PASSWORD = 'admin123'

app = Flask(__name__)
app.config.from_object(Config)
csrf = CSRFProtect(app)

# ---------- EXTENSIONS ----------
db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
mail = Mail(app)

# ---------- MODELS ----------
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='buyer')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    products = db.relationship('Product', backref='seller', lazy=True)
    reviews = db.relationship('Review', backref='author', lazy=True)
    orders = db.relationship('Order', backref='buyer', lazy=True)

class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False)
    price = db.Column(db.Float, nullable=False)
    category = db.Column(db.String(100), nullable=False)
    stock = db.Column(db.Integer, default=0)
    image_url = db.Column(db.String(300), default='https://via.placeholder.com/300')
    views = db.Column(db.Integer, default=0)
    sales_count = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    seller_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    reviews = db.relationship('Review', backref='product', lazy=True)

class Review(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    rating = db.Column(db.Integer, nullable=False)
    comment = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    buyer_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    total_amount = db.Column(db.Float, nullable=False, default=0.0)
    status = db.Column(db.String(20), default='pending')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    items = db.relationship('OrderItem', backref='order', lazy=True, cascade='all, delete-orphan')

class OrderItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('order.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    quantity = db.Column(db.Integer, default=1)
    price = db.Column(db.Float, nullable=False)
    product = db.relationship('Product')

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ---------- FORMS ----------
class LoginForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired()])
    password = PasswordField('Password', validators=[DataRequired()])
    submit = SubmitField('Login')

class RegistrationForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired(), Length(min=3, max=80)])
    email = StringField('Email', validators=[DataRequired()])
    password = PasswordField('Password', validators=[DataRequired(), Length(min=6)])
    role = SelectField('Role', choices=[('buyer', 'I want to buy'), ('seller', 'I want to sell')])
    submit = SubmitField('Register')

    def validate_username(self, field):
        if User.query.filter_by(username=field.data.strip()).first():
            raise ValidationError('Username already taken.')

    def validate_email(self, field):
        email = field.data.strip().lower()
        if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
            raise ValidationError('Invalid email address.')
        if User.query.filter_by(email=email).first():
            raise ValidationError('Email already registered.')

class ReviewForm(FlaskForm):
    rating = SelectField('Rating', choices=[(i, f'{i} ⭐') for i in range(1, 6)], coerce=int)
    comment = TextAreaField('Comment')
    submit = SubmitField('Submit Review')

class ProductForm(FlaskForm):
    name = StringField('Name', validators=[DataRequired()])
    description = TextAreaField('Description', validators=[DataRequired()])
    price = FloatField('Price', validators=[DataRequired(), NumberRange(min=0)])
    category = StringField('Category', validators=[DataRequired()])
    stock = IntegerField('Stock', validators=[DataRequired(), NumberRange(min=0)])
    image_url = StringField('Image URL')
    submit = SubmitField('Save')

class CheckoutForm(FlaskForm):
    submit = SubmitField('Place Order')

# ---------- HELPERS ----------
def send_email(to, subject, body):
    try:
        msg = Message(subject, recipients=[to], body=body)
        mail.send(msg)
        return True
    except Exception as e:
        print(f"[EMAIL] Could not send to {to}: {e}")
        print(f"--- EMAIL TO {to} ---\nSubject: {subject}\nBody: {body}\n---")
        return False

def seed_demo_data():
    if User.query.count() == 0:
        admin = User(
            username='admin',
            email=Config.ADMIN_EMAIL,
            password_hash=generate_password_hash(Config.ADMIN_PASSWORD),
            role='admin'
        )
        seller = User(
            username='seller',
            email='seller@example.com',
            password_hash=generate_password_hash('seller123'),
            role='seller'
        )
        buyer = User(
            username='buyer',
            email='buyer@example.com',
            password_hash=generate_password_hash('buyer123'),
            role='buyer'
        )
        db.session.add_all([admin, seller, buyer])
        db.session.commit()

        products = [
            Product(name='Nova Wireless Headphones', description='Immersive sound for deep focus.',
                    price=3499.00, category='Tech', stock=25,
                    image_url='https://picsum.photos/seed/1/300/300',
                    seller_id=seller.id),
            Product(name='Orbit Smart Watch', description='Track your day, movement, and next big idea.',
                    price=5999.00, category='Tech', stock=12,
                    image_url='https://picsum.photos/seed/2/300/300',
                    seller_id=seller.id),
            Product(name='Cloud Knit Sweater', description='Soft texture, bold comfort, and easy everyday fit.',
                    price=1899.00, category='Fashion', stock=30,
                    image_url='https://picsum.photos/seed/3/300/300',
                    seller_id=seller.id),
            Product(name='Dawn Ceramic Mug', description='A small ritual for calmer mornings.',
                    price=599.00, category='Home', stock=50,
                    image_url='https://picsum.photos/seed/4/300/300',
                    seller_id=seller.id),
            Product(name='Midnight Journal', description='Make space for plans, sketches, and lists.',
                    price=449.00, category='Stationery', stock=40,
                    image_url='https://picsum.photos/seed/5/300/300',
                    seller_id=seller.id),
        ]
        db.session.add_all(products)
        db.session.commit()

# ---------- SCHEMA UPGRADE (auto‑fix missing columns) ----------
def upgrade_schema():
    """Add missing columns to existing tables without dropping data."""
    with app.app_context():
        inspector = db.inspect(db.engine)
        # Check if the 'order' table exists
        if inspector.has_table('order'):
            columns = [col['name'] for col in inspector.get_columns('order')]
            if 'total_amount' not in columns:
                print("Adding missing column 'total_amount' to 'order' table...")
                db.session.execute(text('ALTER TABLE "order" ADD COLUMN total_amount FLOAT DEFAULT 0.0'))
                db.session.commit()
                print("Column added successfully.")

# ---------- INIT DATABASE (runs on app startup) ----------
with app.app_context():
    db.create_all()
    upgrade_schema()
    seed_demo_data()

# ---------- CART ----------
def get_cart():
    return session.get('cart', [])

def save_cart(cart):
    session['cart'] = cart
    session.modified = True

def add_to_cart(product_id, quantity=1):
    cart = get_cart()
    for item in cart:
        if item['product_id'] == product_id:
            item['quantity'] += quantity
            break
    else:
        cart.append({'product_id': product_id, 'quantity': quantity})
    save_cart(cart)

def remove_from_cart(product_id):
    cart = get_cart()
    cart = [item for item in cart if item['product_id'] != product_id]
    save_cart(cart)

def update_cart_quantity(product_id, quantity):
    if quantity <= 0:
        remove_from_cart(product_id)
        return
    cart = get_cart()
    for item in cart:
        if item['product_id'] == product_id:
            item['quantity'] = quantity
            break
    save_cart(cart)

def clear_cart():
    session.pop('cart', None)

def cart_total():
    cart = get_cart()
    total = 0
    for item in cart:
        product = Product.query.get(item['product_id'])
        if product:
            total += product.price * item['quantity']
    return total

def cart_items_count():
    return sum(item['quantity'] for item in get_cart())

# ---------- ROUTES ----------
@app.context_processor
def utility_processor():
    return dict(cart_count=cart_items_count())

@app.route('/')
def index():
    page = request.args.get('page', 1, type=int)
    search = request.args.get('search', '').strip()
    category = request.args.get('category', '').strip()

    query = Product.query
    if search:
        query = query.filter(
            db.or_(
                Product.name.ilike(f'%{search}%'),
                Product.description.ilike(f'%{search}%')
            )
        )
    if category:
        query = query.filter(Product.category == category)

    paginated = query.order_by(Product.created_at.desc()).paginate(
        page=page, per_page=Config.ITEMS_PER_PAGE, error_out=False
    )
    products = paginated.items
    categories = db.session.query(Product.category).distinct().all()
    categories = [c[0] for c in categories]

    return render_template_string(INDEX_HTML, products=products, categories=categories,
                                  search=search, category=category, pagination=paginated)

@app.route('/product/<int:id>')
def product_detail(id):
    product = Product.query.get_or_404(id)
    product.views += 1
    db.session.commit()
    form = ReviewForm()
    reviews = Review.query.filter_by(product_id=id).order_by(Review.created_at.desc()).all()
    avg_rating = db.session.query(db.func.avg(Review.rating)).filter_by(product_id=id).scalar() or 0
    return render_template_string(PRODUCT_DETAIL_HTML, product=product, form=form,
                                  reviews=reviews, avg_rating=avg_rating)

@app.route('/review/<int:product_id>', methods=['POST'])
@login_required
def add_review(product_id):
    product = Product.query.get_or_404(product_id)
    form = ReviewForm()
    if form.validate_on_submit():
        review = Review(
            rating=form.rating.data,
            comment=form.comment.data,
            product_id=product_id,
            user_id=current_user.id
        )
        db.session.add(review)
        db.session.commit()
        flash('Review submitted!', 'success')
    else:
        flash('Invalid review data.', 'danger')
    return redirect(url_for('product_detail', id=product_id))

@app.route('/cart')
def cart():
    cart_items = []
    total = 0
    for item in get_cart():
        product = Product.query.get(item['product_id'])
        if product:
            cart_items.append({'product': product, 'quantity': item['quantity']})
            total += product.price * item['quantity']
    return render_template_string(CART_HTML, cart_items=cart_items, total=total)

@app.route('/add_to_cart/<int:product_id>', methods=['POST'])
@login_required
def add_to_cart_route(product_id):
    quantity = request.form.get('quantity', 1, type=int)
    add_to_cart(product_id, quantity)
    flash('Added to cart!', 'success')
    return redirect(request.referrer or url_for('index'))

@app.route('/update_cart', methods=['POST'])
@login_required
def update_cart():
    product_id = request.form.get('product_id', type=int)
    quantity = request.form.get('quantity', 0, type=int)
    if product_id:
        update_cart_quantity(product_id, quantity)
    return redirect(url_for('cart'))

@app.route('/remove_from_cart/<int:product_id>', methods=['POST'])
@login_required
def remove_from_cart_route(product_id):
    remove_from_cart(product_id)
    flash('Removed from cart.', 'info')
    return redirect(url_for('cart'))

@app.route('/checkout', methods=['GET', 'POST'])
@login_required
def checkout():
    form = CheckoutForm()
    cart_items = get_cart()
    if not cart_items:
        flash('Your cart is empty.', 'warning')
        return redirect(url_for('index'))

    if form.validate_on_submit():
        total = cart_total()
        order = Order(
            buyer_id=current_user.id,
            total_amount=total,
            status='paid'
        )
        db.session.add(order)
        db.session.commit()

        for item in cart_items:
            product = Product.query.get(item['product_id'])
            if product and product.stock >= item['quantity']:
                product.stock -= item['quantity']
                product.sales_count += item['quantity']
                order_item = OrderItem(
                    order_id=order.id,
                    product_id=product.id,
                    quantity=item['quantity'],
                    price=product.price
                )
                db.session.add(order_item)
            else:
                flash(f'Not enough stock for {product.name}.', 'danger')
                db.session.rollback()
                return redirect(url_for('cart'))

        db.session.commit()
        clear_cart()
        send_email(current_user.email, 'Order Confirmation',
                   f'Your order #{order.id} has been placed. Total: ₹{total:.2f}')
        flash(f'Order #{order.id} placed successfully!', 'success')
        return redirect(url_for('orders'))

    return render_template_string(CHECKOUT_HTML, form=form, total=cart_total())

@app.route('/orders')
@login_required
def orders():
    orders = Order.query.filter_by(buyer_id=current_user.id).order_by(Order.created_at.desc()).all()
    return render_template_string(ORDERS_HTML, orders=orders)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    form = LoginForm()
    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        password = form.password.data
        user = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            flash('Logged in successfully.', 'success')
            next_page = request.args.get('next')
            return redirect(next_page) if next_page else redirect(url_for('index'))
        flash('Invalid email or password.', 'danger')
    return render_template_string(LOGIN_HTML, form=form)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    form = RegistrationForm()
    if form.validate_on_submit():
        username = form.username.data.strip()
        email = form.email.data.strip().lower()
        password = form.password.data
        role = form.role.data
        user = User(username=username, email=email,
                    password_hash=generate_password_hash(password), role=role)
        db.session.add(user)
        db.session.commit()
        send_email(email, 'Welcome to Marketplace', f'Hi {username},\nThanks for joining!')
        flash('Registration successful! Please log in.', 'success')
        return redirect(url_for('login'))
    return render_template_string(REGISTER_HTML, form=form)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('index'))

# ---------- SELLER DASHBOARD ----------
@app.route('/dashboard')
@login_required
def dashboard():
    if current_user.role not in ('seller', 'admin'):
        flash('Access denied.', 'danger')
        return redirect(url_for('index'))
    products = Product.query.filter_by(seller_id=current_user.id).all()
    total_views = sum(p.views for p in products)
    total_sales = sum(p.sales_count for p in products)
    total_revenue = sum(p.price * p.sales_count for p in products)
    conversion_rate = (total_sales / total_views * 100) if total_views > 0 else 0
    product_ids = [p.id for p in products]
    recent_orders = Order.query.filter(Order.id.in_(
        db.session.query(OrderItem.order_id).filter(OrderItem.product_id.in_(product_ids))
    )).order_by(Order.created_at.desc()).limit(10).all()
    return render_template_string(DASHBOARD_HTML, products=products,
                                  total_views=total_views, total_sales=total_sales,
                                  total_revenue=total_revenue, conversion_rate=conversion_rate,
                                  recent_orders=recent_orders)

@app.route('/add_product', methods=['GET', 'POST'])
@login_required
def add_product():
    if current_user.role not in ('seller', 'admin'):
        flash('Access denied.', 'danger')
        return redirect(url_for('index'))
    form = ProductForm()
    if form.validate_on_submit():
        product = Product(
            name=form.name.data, description=form.description.data,
            price=form.price.data, category=form.category.data,
            stock=form.stock.data, image_url=form.image_url.data or 'https://picsum.photos/seed/random/300/300',
            seller_id=current_user.id
        )
        db.session.add(product)
        db.session.commit()
        flash('Product added!', 'success')
        return redirect(url_for('dashboard'))
    return render_template_string(ADD_PRODUCT_HTML, form=form)

@app.route('/edit_product/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_product(id):
    product = Product.query.get_or_404(id)
    if product.seller_id != current_user.id and current_user.role != 'admin':
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard'))
    form = ProductForm(obj=product)
    if form.validate_on_submit():
        form.populate_obj(product)
        db.session.commit()
        flash('Product updated!', 'success')
        return redirect(url_for('dashboard'))
    return render_template_string(EDIT_PRODUCT_HTML, form=form, product=product)

@app.route('/delete_product/<int:id>', methods=['POST'])
@login_required
def delete_product(id):
    product = Product.query.get_or_404(id)
    if product.seller_id != current_user.id and current_user.role != 'admin':
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard'))
    db.session.delete(product)
    db.session.commit()
    flash('Product deleted.', 'success')
    return redirect(url_for('dashboard'))

# ---------- ADMIN PANEL ----------
@app.route('/admin')
@login_required
def admin_panel():
    if current_user.role != 'admin':
        flash('Admin access required.', 'danger')
        return redirect(url_for('index'))
    users = User.query.all()
    products = Product.query.all()
    orders = Order.query.all()
    return render_template_string(ADMIN_HTML, users=users, products=products, orders=orders)

@app.route('/admin/user/<int:user_id>/toggle_role', methods=['POST'])
@login_required
def admin_toggle_role(user_id):
    if current_user.role != 'admin':
        flash('Access denied.', 'danger')
        return redirect(url_for('index'))
    user = User.query.get_or_404(user_id)
    if user.role == 'admin':
        flash('Cannot change admin role.', 'warning')
    else:
        user.role = 'seller' if user.role == 'buyer' else 'buyer'
        db.session.commit()
        flash(f'User {user.username} role changed to {user.role}.', 'success')
    return redirect(url_for('admin_panel'))

@app.route('/admin/order/<int:order_id>/update_status', methods=['POST'])
@login_required
def admin_update_order_status(order_id):
    if current_user.role != 'admin':
        flash('Access denied.', 'danger')
        return redirect(url_for('index'))
    order = Order.query.get_or_404(order_id)
    new_status = request.form.get('status')
    if new_status in ('pending', 'paid', 'shipped', 'delivered', 'cancelled'):
        order.status = new_status
        db.session.commit()
        flash(f'Order #{order.id} status updated to {new_status}.', 'success')
        send_email(order.buyer.email, f'Order #{order.id} Status Update',
                   f'Your order status is now: {new_status}')
    else:
        flash('Invalid status.', 'danger')
    return redirect(url_for('admin_panel'))

# ---------- EMBEDDED TEMPLATES ----------
INDEX_HTML = '''
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>🛍️ Marketplace</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        body { background: #f4f6f9; font-family: 'Segoe UI', sans-serif; }
        .navbar-brand { font-weight: 700; }
        .card { border: none; border-radius: 16px; transition: transform 0.2s, box-shadow 0.2s; overflow: hidden; }
        .card:hover { transform: translateY(-4px); box-shadow: 0 12px 28px rgba(0,0,0,0.08); }
        .card-img-top { height: 200px; object-fit: cover; background: #fff; padding: 0; }
        .product-category { font-size: 0.75rem; font-weight: 600; text-transform: uppercase; color: #6c757d; letter-spacing: 0.5px; }
        .product-price { font-weight: 700; color: #2c7a4d; font-size: 1.1rem; }
        .btn-outline-primary { border-radius: 30px; }
        .search-form .form-control, .search-form .form-select { border-radius: 30px; }
        .search-form .btn { border-radius: 30px; }
        .badge-cart { background: #dc3545; color: white; border-radius: 50%; padding: 0.25rem 0.5rem; font-size: 0.75rem; }
        .pagination .page-link { border-radius: 30px; margin: 0 4px; color: #2c7a4d; }
        .pagination .active .page-link { background: #2c7a4d; border-color: #2c7a4d; color: white; }
        footer { border-top: 1px solid #dee2e6; padding: 20px 0; margin-top: 30px; color: #6c757d; }
    </style>
</head>
<body>
<nav class="navbar navbar-expand-lg navbar-dark bg-dark shadow-sm">
    <div class="container">
        <a class="navbar-brand" href="/"><i class="fas fa-store me-2"></i>Marketplace</a>
        <button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#navbarNav">
            <span class="navbar-toggler-icon"></span>
        </button>
        <div class="collapse navbar-collapse" id="navbarNav">
            <ul class="navbar-nav ms-auto">
                {% if current_user.is_authenticated %}
                    <li class="nav-item"><a class="nav-link" href="/dashboard"><i class="fas fa-chart-line me-1"></i>Dashboard</a></li>
                    <li class="nav-item"><a class="nav-link" href="/orders"><i class="fas fa-box me-1"></i>Orders</a></li>
                    <li class="nav-item"><a class="nav-link position-relative" href="/cart">
                        <i class="fas fa-shopping-cart"></i>
                        {% if cart_count > 0 %}<span class="badge-cart position-absolute top-0 start-100 translate-middle">{{ cart_count }}</span>{% endif %}
                    </a></li>
                    <li class="nav-item"><a class="nav-link" href="/logout"><i class="fas fa-sign-out-alt me-1"></i>Logout</a></li>
                {% else %}
                    <li class="nav-item"><a class="nav-link" href="/login"><i class="fas fa-sign-in-alt me-1"></i>Login</a></li>
                    <li class="nav-item"><a class="nav-link" href="/register"><i class="fas fa-user-plus me-1"></i>Register</a></li>
                {% endif %}
            </ul>
        </div>
    </div>
</nav>

<div class="container my-4">
    {% with messages = get_flashed_messages(with_categories=true) %}
        {% if messages %}
            {% for cat, msg in messages %}
                <div class="alert alert-{{ cat }} alert-dismissible fade show" role="alert">
                    <i class="fas fa-{% if cat == 'success' %}check-circle{% elif cat == 'danger' %}exclamation-circle{% elif cat == 'warning' %}exclamation-triangle{% else %}info-circle{% endif %} me-2"></i>
                    {{ msg }}
                    <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
                </div>
            {% endfor %}
        {% endif %}
    {% endwith %}

    <div class="row mb-4">
        <div class="col">
            <form method="get" class="row g-2 search-form">
                <div class="col-md-5">
                    <input class="form-control" name="search" placeholder="Search products..." value="{{ search }}">
                </div>
                <div class="col-md-4">
                    <select class="form-select" name="category">
                        <option value="">All Categories</option>
                        {% for cat in categories %}
                            <option value="{{ cat }}" {% if cat == category %}selected{% endif %}>{{ cat }}</option>
                        {% endfor %}
                    </select>
                </div>
                <div class="col-md-3">
                    <button class="btn btn-primary w-100" type="submit"><i class="fas fa-search me-1"></i>Filter</button>
                </div>
            </form>
        </div>
    </div>

    <div class="row row-cols-1 row-cols-md-3 g-4">
        {% for product in products %}
            <div class="col">
                <div class="card h-100">
                    <img src="{{ product.image_url }}" class="card-img-top" alt="{{ product.name }}" onerror="this.onerror=null; this.src='https://picsum.photos/seed/{{ product.id }}/300/300'">
                    <div class="card-body">
                        <span class="product-category">{{ product.category }}</span>
                        <h5 class="card-title mt-1">{{ product.name }}</h5>
                        <p class="card-text small text-muted">{{ product.description[:80] }}…</p>
                        <div class="d-flex justify-content-between align-items-center">
                            <span class="product-price">₹{{ "%.2f"|format(product.price) }}</span>
                            <a href="/product/{{ product.id }}" class="btn btn-outline-primary btn-sm"><i class="fas fa-eye me-1"></i>View</a>
                        </div>
                    </div>
                </div>
            </div>
        {% else %}
            <div class="col-12 text-center py-5">
                <i class="fas fa-box-open fa-3x text-muted mb-3"></i>
                <h4>No products found</h4>
                <p class="text-muted">Try adjusting your search or filter.</p>
            </div>
        {% endfor %}
    </div>

    <nav aria-label="Page navigation">
        <ul class="pagination justify-content-center">
            {% if pagination.has_prev %}
                <li class="page-item"><a class="page-link" href="{{ url_for('index', page=pagination.prev_num, search=search, category=category) }}"><i class="fas fa-chevron-left"></i></a></li>
            {% endif %}
            {% for p in pagination.iter_pages() %}
                {% if p %}
                    <li class="page-item {% if p == pagination.page %}active{% endif %}">
                        <a class="page-link" href="{{ url_for('index', page=p, search=search, category=category) }}">{{ p }}</a>
                    </li>
                {% else %}
                    <li class="page-item disabled"><span class="page-link">…</span></li>
                {% endif %}
            {% endfor %}
            {% if pagination.has_next %}
                <li class="page-item"><a class="page-link" href="{{ url_for('index', page=pagination.next_num, search=search, category=category) }}"><i class="fas fa-chevron-right"></i></a></li>
            {% endif %}
        </ul>
    </nav>

    <footer class="text-center">
        <small>&copy; 2026 Marketplace – All rights reserved.</small>
    </footer>
</div>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
'''

PRODUCT_DETAIL_HTML = '''
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{{ product.name }}</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        body { background: #f4f6f9; }
        .product-image { max-height: 400px; object-fit: cover; background: #fff; border-radius: 16px; padding: 0; width: 100%; }
        .detail-card { border: none; border-radius: 20px; box-shadow: 0 8px 24px rgba(0,0,0,0.06); }
        .price-large { font-size: 2.2rem; font-weight: 700; color: #2c7a4d; }
        .star-rating { color: #ffc107; font-size: 1.1rem; }
        .review-card { border-left: 3px solid #2c7a4d; background: #f8f9fa; }
    </style>
</head>
<body>
<nav class="navbar navbar-dark bg-dark shadow-sm">
    <div class="container">
        <a class="navbar-brand" href="/"><i class="fas fa-store me-2"></i>Marketplace</a>
        <a href="/" class="btn btn-outline-light btn-sm"><i class="fas fa-arrow-left me-1"></i>Back</a>
    </div>
</nav>

<div class="container my-5">
    <div class="row g-4">
        <div class="col-md-6">
            <img src="{{ product.image_url }}" class="product-image img-fluid w-100" alt="{{ product.name }}" onerror="this.onerror=null; this.src='https://picsum.photos/seed/{{ product.id }}/400/400'">
        </div>
        <div class="col-md-6">
            <div class="detail-card p-4 bg-white">
                <span class="badge bg-secondary mb-2">{{ product.category }}</span>
                <h1 class="display-6 fw-bold">{{ product.name }}</h1>
                <p class="text-muted">{{ product.description }}</p>
                <div class="price-large">₹{{ "%.2f"|format(product.price) }}</div>
                <div class="mt-2">
                    <span class="star-rating">
                        {% for i in range(5) %}
                            <i class="fas fa-star{% if i >= avg_rating|int %}-o text-muted{% endif %}"></i>
                        {% endfor %}
                    </span>
                    <span class="text-muted ms-2">({{ avg_rating|round(1) }} avg, {{ reviews|length }} reviews)</span>
                </div>
                <p class="mt-2"><i class="fas fa-box me-2"></i><strong>Stock:</strong> {{ product.stock }}</p>
                <p><i class="fas fa-user me-2"></i><strong>Seller:</strong> {{ product.seller.username }}</p>

                {% if current_user.is_authenticated and current_user.role == 'buyer' %}
                    <form method="post" action="/add_to_cart/{{ product.id }}" class="mt-3">
                        <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
                        <div class="row g-2 align-items-center">
                            <div class="col-3">
                                <input class="form-control" type="number" name="quantity" value="1" min="1" max="{{ product.stock }}">
                            </div>
                            <div class="col-4">
                                <button class="btn btn-success w-100" type="submit"><i class="fas fa-cart-plus me-1"></i>Add to Cart</button>
                            </div>
                        </div>
                    </form>
                {% elif current_user.is_authenticated and current_user.role == 'seller' %}
                    <div class="alert alert-info mt-3"><i class="fas fa-info-circle me-2"></i>You are a seller – you can't buy your own products.</div>
                {% else %}
                    <a href="/login" class="btn btn-primary mt-3"><i class="fas fa-sign-in-alt me-1"></i>Login to Buy</a>
                {% endif %}
            </div>

            <!-- Reviews -->
            <div class="mt-4">
                <h4><i class="fas fa-comments me-2"></i>Reviews</h4>
                {% if current_user.is_authenticated and current_user.role == 'buyer' %}
                    <div class="card p-3 mb-3">
                        <form method="post" action="/review/{{ product.id }}">
                            {{ form.csrf_token }}
                            <div class="row g-2">
                                <div class="col-3">
                                    {{ form.rating(class="form-select") }}
                                </div>
                                <div class="col-6">
                                    {{ form.comment(class="form-control", placeholder="Your comment...") }}
                                </div>
                                <div class="col-3">
                                    <button class="btn btn-primary w-100" type="submit"><i class="fas fa-paper-plane me-1"></i>Submit</button>
                                </div>
                            </div>
                        </form>
                    </div>
                {% endif %}
                {% for review in reviews %}
                    <div class="review-card p-3 mb-2">
                        <div>
                            <span class="star-rating">
                                {% for i in range(5) %}
                                    <i class="fas fa-star{% if i >= review.rating %}-o text-muted{% endif %}"></i>
                                {% endfor %}
                            </span>
                            <span class="fw-bold ms-2">{{ review.author.username }}</span>
                            <span class="text-muted small float-end">{{ review.created_at.strftime('%d %b %Y') }}</span>
                        </div>
                        <p class="mt-1 mb-0">{{ review.comment or 'No comment.' }}</p>
                    </div>
                {% else %}
                    <p class="text-muted">No reviews yet. Be the first!</p>
                {% endfor %}
            </div>
        </div>
    </div>
</div>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
'''

CART_HTML = '''
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Shopping Cart</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        body { background: #f4f6f9; }
        .cart-item { border-bottom: 1px solid #dee2e6; padding: 15px 0; }
        .cart-item:last-child { border-bottom: none; }
        .qty-input { width: 60px; text-align: center; }
        .cart-img { width: 80px; height: 80px; object-fit: cover; border-radius: 8px; }
    </style>
</head>
<body>
<nav class="navbar navbar-dark bg-dark shadow-sm">
    <div class="container">
        <a class="navbar-brand" href="/"><i class="fas fa-store me-2"></i>Marketplace</a>
        <a href="/" class="btn btn-outline-light btn-sm"><i class="fas fa-arrow-left me-1"></i>Continue Shopping</a>
    </div>
</nav>

<div class="container my-4">
    <h2><i class="fas fa-shopping-cart me-2"></i>Your Cart</h2>
    {% if cart_items %}
        <div class="card p-3">
            {% for item in cart_items %}
                <div class="cart-item d-flex align-items-center">
                    <img src="{{ item.product.image_url }}" class="cart-img" alt="{{ item.product.name }}" onerror="this.onerror=null; this.src='https://picsum.photos/seed/{{ item.product.id }}/80/80'">
                    <div class="flex-grow-1 ms-3">
                        <h5>{{ item.product.name }}</h5>
                        <span class="text-muted">₹{{ "%.2f"|format(item.product.price) }}</span>
                    </div>
                    <div class="d-flex align-items-center">
                        <form method="post" action="/update_cart" class="d-flex align-items-center">
                            <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
                            <input type="hidden" name="product_id" value="{{ item.product.id }}">
                            <input type="number" name="quantity" value="{{ item.quantity }}" min="1" class="form-control qty-input me-2">
                            <button class="btn btn-sm btn-outline-primary me-2" type="submit"><i class="fas fa-sync-alt"></i></button>
                        </form>
                        <form method="post" action="/remove_from_cart/{{ item.product.id }}">
                            <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
                            <button class="btn btn-sm btn-danger"><i class="fas fa-trash-alt"></i></button>
                        </form>
                    </div>
                </div>
            {% endfor %}
            <div class="d-flex justify-content-between align-items-center mt-3">
                <h4>Total: <span class="text-success">₹{{ "%.2f"|format(total) }}</span></h4>
                <a href="/checkout" class="btn btn-success btn-lg"><i class="fas fa-credit-card me-1"></i>Proceed to Checkout</a>
            </div>
        </div>
    {% else %}
        <div class="text-center py-5">
            <i class="fas fa-shopping-cart fa-4x text-muted mb-3"></i>
            <h4>Your cart is empty</h4>
            <a href="/" class="btn btn-primary">Start Shopping</a>
        </div>
    {% endif %}
</div>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
'''

CHECKOUT_HTML = '''
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Checkout</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
</head>
<body>
<nav class="navbar navbar-dark bg-dark shadow-sm">
    <div class="container">
        <a class="navbar-brand" href="/"><i class="fas fa-store me-2"></i>Marketplace</a>
    </div>
</nav>

<div class="container my-4" style="max-width:600px;">
    <div class="card p-4">
        <h3><i class="fas fa-credit-card me-2"></i>Checkout</h3>
        <p class="text-muted">Total amount: <strong>₹{{ "%.2f"|format(total) }}</strong></p>
        <form method="post">
            {{ form.csrf_token }}
            <div class="alert alert-info"><i class="fas fa-info-circle me-2"></i>This is a demo – your order will be placed without real payment.</div>
            <button type="submit" class="btn btn-success w-100"><i class="fas fa-check me-2"></i>Place Order</button>
        </form>
        <a href="/cart" class="btn btn-outline-secondary w-100 mt-2"><i class="fas fa-arrow-left me-1"></i>Back to Cart</a>
    </div>
</div>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
'''

ORDERS_HTML = '''
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>My Orders</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
</head>
<body>
<nav class="navbar navbar-dark bg-dark shadow-sm">
    <div class="container">
        <a class="navbar-brand" href="/"><i class="fas fa-store me-2"></i>Marketplace</a>
        <a href="/" class="btn btn-outline-light btn-sm"><i class="fas fa-arrow-left me-1"></i>Shop</a>
    </div>
</nav>

<div class="container my-4">
    <h2><i class="fas fa-box me-2"></i>My Orders</h2>
    {% if orders %}
        <div class="list-group">
            {% for order in orders %}
                <div class="list-group-item">
                    <div class="d-flex justify-content-between align-items-center">
                        <div>
                            <strong>Order #{{ order.id }}</strong>
                            <span class="badge bg-{% if order.status == 'paid' %}success{% elif order.status == 'pending' %}warning{% elif order.status == 'shipped' %}info{% elif order.status == 'delivered' %}primary{% else %}secondary{% endif %} ms-2">{{ order.status }}</span>
                        </div>
                        <span class="text-muted">{{ order.created_at.strftime('%d %b %Y, %H:%M') }}</span>
                    </div>
                    <div class="mt-2">
                        <span class="fw-bold">Total: ₹{{ "%.2f"|format(order.total_amount) }}</span>
                    </div>
                    <div class="mt-1">
                        {% for item in order.items %}
                            <span class="badge bg-light text-dark me-1">{{ item.product.name }} × {{ item.quantity }}</span>
                        {% endfor %}
                    </div>
                </div>
            {% endfor %}
        </div>
    {% else %}
        <div class="text-center py-5">
            <i class="fas fa-box-open fa-4x text-muted mb-3"></i>
            <h4>No orders yet</h4>
            <a href="/" class="btn btn-primary">Start Shopping</a>
        </div>
    {% endif %}
</div>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
'''

LOGIN_HTML = '''
<!DOCTYPE html>
<html>
<head><title>Login</title><link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet"><link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css"></head>
<body>
<div class="container" style="max-width:400px; margin-top:100px;">
    <div class="card shadow-sm p-4">
        <h2 class="mb-3"><i class="fas fa-sign-in-alt me-2"></i>Welcome Back</h2>
        <form method="post">
            {{ form.csrf_token }}
            <div class="mb-3">{{ form.email(class="form-control", placeholder="Email") }}</div>
            <div class="mb-3">{{ form.password(class="form-control", placeholder="Password") }}</div>
            <button class="btn btn-primary w-100" type="submit"><i class="fas fa-arrow-right me-1"></i>{{ form.submit.label.text }}</button>
        </form>
        <p class="mt-3 text-center">Don't have an account? <a href="/register">Register</a></p>
    </div>
</div>
</body>
</html>
'''

REGISTER_HTML = '''
<!DOCTYPE html>
<html>
<head><title>Register</title><link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet"><link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css"></head>
<body>
<div class="container" style="max-width:400px; margin-top:100px;">
    <div class="card shadow-sm p-4">
        <h2 class="mb-3"><i class="fas fa-user-plus me-2"></i>Join Marketplace</h2>
        <form method="post">
            {{ form.csrf_token }}
            <div class="mb-3">{{ form.username(class="form-control", placeholder="Username") }}</div>
            <div class="mb-3">{{ form.email(class="form-control", placeholder="Email") }}</div>
            <div class="mb-3">{{ form.password(class="form-control", placeholder="Password") }}</div>
            <div class="mb-3">{{ form.role(class="form-select") }}</div>
            <button class="btn btn-primary w-100" type="submit"><i class="fas fa-user-check me-1"></i>{{ form.submit.label.text }}</button>
        </form>
        <p class="mt-3 text-center">Already registered? <a href="/login">Login</a></p>
    </div>
</div>
</body>
</html>
'''

DASHBOARD_HTML = '''
<!DOCTYPE html>
<html>
<head><title>Seller Dashboard</title><link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet"><link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css"></head>
<style>
    .stat-card { border: none; border-radius: 16px; box-shadow: 0 4px 12px rgba(0,0,0,0.05); }
    .stat-number { font-size: 2rem; font-weight: 700; }
</style>
<body>
<nav class="navbar navbar-dark bg-dark shadow-sm">
    <div class="container">
        <a class="navbar-brand" href="/"><i class="fas fa-store me-2"></i>Dashboard</a>
        <a href="/logout" class="btn btn-outline-light btn-sm"><i class="fas fa-sign-out-alt me-1"></i>Logout</a>
    </div>
</nav>

<div class="container my-4">
    <h2 class="mb-4"><i class="fas fa-chart-line me-2"></i>Welcome, {{ current_user.username }}</h2>

    <div class="row g-3 mb-4">
        <div class="col-md-3">
            <div class="stat-card card p-3">
                <h6 class="text-muted"><i class="fas fa-eye me-1"></i>Total Views</h6>
                <div class="stat-number">{{ total_views }}</div>
            </div>
        </div>
        <div class="col-md-3">
            <div class="stat-card card p-3">
                <h6 class="text-muted"><i class="fas fa-shopping-bag me-1"></i>Total Sales</h6>
                <div class="stat-number">{{ total_sales }}</div>
            </div>
        </div>
        <div class="col-md-3">
            <div class="stat-card card p-3">
                <h6 class="text-muted"><i class="fas fa-coins me-1"></i>Revenue</h6>
                <div class="stat-number text-success">₹{{ "%.2f"|format(total_revenue) }}</div>
            </div>
        </div>
        <div class="col-md-3">
            <div class="stat-card card p-3">
                <h6 class="text-muted"><i class="fas fa-percent me-1"></i>Conversion Rate</h6>
                <div class="stat-number">{{ "%.1f"|format(conversion_rate) }}%</div>
            </div>
        </div>
    </div>

    <div class="d-flex justify-content-between align-items-center mb-3">
        <h3><i class="fas fa-boxes me-2"></i>My Products</h3>
        <a href="/add_product" class="btn btn-success"><i class="fas fa-plus me-1"></i>Add Product</a>
    </div>
    <div class="table-responsive">
        <table class="table table-hover align-middle">
            <thead class="table-light">
                <tr>
                    <th>Name</th>
                    <th>Price</th>
                    <th>Stock</th>
                    <th>Views</th>
                    <th>Sales</th>
                    <th>Actions</th>
                </tr>
            </thead>
            <tbody>
                {% for p in products %}
                <tr>
                    <td>{{ p.name }}</td>
                    <td>₹{{ "%.2f"|format(p.price) }}</td>
                    <td>{{ p.stock }}</td>
                    <td>{{ p.views }}</td>
                    <td>{{ p.sales_count }}</td>
                    <td>
                        <a href="/edit_product/{{ p.id }}" class="btn btn-sm btn-warning"><i class="fas fa-edit"></i></a>
                        <form method="post" action="/delete_product/{{ p.id }}" style="display:inline;" onsubmit="return confirm('Delete this product?')">
                            <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
                            <button class="btn btn-sm btn-danger"><i class="fas fa-trash-alt"></i></button>
                        </form>
                    </td>
                </tr>
                {% else %}
                <tr><td colspan="6" class="text-center py-4">You haven't added any products yet.</td></tr>
                {% endfor %}
            </tbody>
        </table>
    </div>

    <h4 class="mt-4"><i class="fas fa-clock me-2"></i>Recent Orders</h4>
    <div class="table-responsive">
        <table class="table table-sm">
            <thead><tr><th>Product</th><th>Qty</th><th>Total</th><th>Buyer</th><th>Date</th></tr></thead>
            <tbody>
                {% for order in recent_orders %}
                <tr>
                    <td>{{ order.product.name }}</td>
                    <td>{{ order.quantity }}</td>
                    <td>₹{{ "%.2f"|format(order.total_price) }}</td>
                    <td>{{ order.buyer.username }}</td>
                    <td>{{ order.created_at.strftime('%Y-%m-%d') }}</td>
                </tr>
                {% else %}
                <tr><td colspan="5" class="text-center">No orders yet.</td></tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
</div>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
'''

ADD_PRODUCT_HTML = '''
<!DOCTYPE html>
<html>
<head><title>Add Product</title><link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet"><link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css"></head>
<body>
<div class="container" style="max-width:600px; margin-top:60px;">
    <div class="card shadow-sm p-4">
        <h2 class="mb-3"><i class="fas fa-plus-circle me-2"></i>Add New Product</h2>
        <form method="post">
            {{ form.csrf_token }}
            <div class="mb-2">{{ form.name(class="form-control", placeholder="Product Name") }}</div>
            <div class="mb-2">{{ form.description(class="form-control", rows=3, placeholder="Description") }}</div>
            <div class="mb-2">{{ form.price(class="form-control", placeholder="Price (₹)") }}</div>
            <div class="mb-2">{{ form.category(class="form-control", placeholder="Category") }}</div>
            <div class="mb-2">{{ form.stock(class="form-control", placeholder="Stock") }}</div>
            <div class="mb-2">{{ form.image_url(class="form-control", placeholder="Image URL (optional)") }}</div>
            <button class="btn btn-primary" type="submit"><i class="fas fa-save me-1"></i>Add Product</button>
            <a href="/dashboard" class="btn btn-secondary"><i class="fas fa-times me-1"></i>Cancel</a>
        </form>
    </div>
</div>
</body>
</html>
'''

EDIT_PRODUCT_HTML = '''
<!DOCTYPE html>
<html>
<head><title>Edit Product</title><link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet"><link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css"></head>
<body>
<div class="container" style="max-width:600px; margin-top:60px;">
    <div class="card shadow-sm p-4">
        <h2 class="mb-3"><i class="fas fa-edit me-2"></i>Edit Product</h2>
        <form method="post">
            {{ form.csrf_token }}
            <div class="mb-2">{{ form.name(class="form-control", placeholder="Product Name") }}</div>
            <div class="mb-2">{{ form.description(class="form-control", rows=3, placeholder="Description") }}</div>
            <div class="mb-2">{{ form.price(class="form-control", placeholder="Price (₹)") }}</div>
            <div class="mb-2">{{ form.category(class="form-control", placeholder="Category") }}</div>
            <div class="mb-2">{{ form.stock(class="form-control", placeholder="Stock") }}</div>
            <div class="mb-2">{{ form.image_url(class="form-control", placeholder="Image URL") }}</div>
            <button class="btn btn-primary" type="submit"><i class="fas fa-save me-1"></i>Update</button>
            <a href="/dashboard" class="btn btn-secondary"><i class="fas fa-times me-1"></i>Cancel</a>
        </form>
    </div>
</div>
</body>
</html>
'''

ADMIN_HTML = '''
<!DOCTYPE html>
<html>
<head><title>Admin Panel</title><link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet"><link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css"></head>
<style>
    .admin-card { border: none; border-radius: 16px; box-shadow: 0 4px 12px rgba(0,0,0,0.05); }
</style>
<body>
<nav class="navbar navbar-dark bg-dark shadow-sm">
    <div class="container">
        <a class="navbar-brand" href="/"><i class="fas fa-store me-2"></i>Admin Panel</a>
        <a href="/logout" class="btn btn-outline-light btn-sm"><i class="fas fa-sign-out-alt me-1"></i>Logout</a>
    </div>
</nav>

<div class="container my-4">
    <h2><i class="fas fa-user-shield me-2"></i>Administration</h2>
    <ul class="nav nav-tabs mt-3" id="adminTabs" role="tablist">
        <li class="nav-item"><button class="nav-link active" data-bs-toggle="tab" data-bs-target="#users">Users</button></li>
        <li class="nav-item"><button class="nav-link" data-bs-toggle="tab" data-bs-target="#products">Products</button></li>
        <li class="nav-item"><button class="nav-link" data-bs-toggle="tab" data-bs-target="#orders">Orders</button></li>
    </ul>

    <div class="tab-content mt-3">
        <!-- Users -->
        <div class="tab-pane fade show active" id="users">
            <div class="table-responsive">
                <table class="table table-striped">
                    <thead><tr><th>ID</th><th>Username</th><th>Email</th><th>Role</th><th>Action</th></tr></thead>
                    <tbody>
                        {% for user in users %}
                        <tr>
                            <td>{{ user.id }}</td>
                            <td>{{ user.username }}</td>
                            <td>{{ user.email }}</td>
                            <td><span class="badge bg-{% if user.role == 'admin' %}danger{% elif user.role == 'seller' %}warning{% else %}info{% endif %}">{{ user.role }}</span></td>
                            <td>
                                {% if user.role != 'admin' %}
                                <form method="post" action="/admin/user/{{ user.id }}/toggle_role" style="display:inline;">
                                    <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
                                    <button class="btn btn-sm btn-outline-primary"><i class="fas fa-exchange-alt me-1"></i>Toggle Role</button>
                                </form>
                                {% endif %}
                            </td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>

        <!-- Products -->
        <div class="tab-pane fade" id="products">
            <table class="table table-striped">
                <thead><tr><th>ID</th><th>Name</th><th>Price</th><th>Stock</th><th>Seller</th></tr></thead>
                <tbody>
                    {% for p in products %}
                    <tr><td>{{ p.id }}</td><td>{{ p.name }}</td><td>₹{{ "%.2f"|format(p.price) }}</td><td>{{ p.stock }}</td><td>{{ p.seller.username }}</td></tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>

        <!-- Orders -->
        <div class="tab-pane fade" id="orders">
            <table class="table table-striped">
                <thead><tr><th>ID</th><th>Buyer</th><th>Total</th><th>Status</th><th>Action</th></tr></thead>
                <tbody>
                    {% for order in orders %}
                    <tr>
                        <td>{{ order.id }}</td>
                        <td>{{ order.buyer.username }}</td>
                        <td>₹{{ "%.2f"|format(order.total_amount) }}</td>
                        <td><span class="badge bg-{% if order.status == 'paid' %}success{% elif order.status == 'pending' %}warning{% elif order.status == 'shipped' %}info{% elif order.status == 'delivered' %}primary{% else %}secondary{% endif %}">{{ order.status }}</span></td>
                        <td>
                            <form method="post" action="/admin/order/{{ order.id }}/update_status" class="d-flex">
                                <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
                                <select name="status" class="form-select form-select-sm me-2">
                                    <option value="pending">pending</option>
                                    <option value="paid">paid</option>
                                    <option value="shipped">shipped</option>
                                    <option value="delivered">delivered</option>
                                    <option value="cancelled">cancelled</option>
                                </select>
                                <button class="btn btn-sm btn-primary" type="submit">Update</button>
                            </form>
                        </td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
    </div>
</div>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
'''

# ---------- UNIT TESTS ----------
def run_tests():
    suite = unittest.TestSuite()
    suite.addTest(unittest.defaultTestLoader.loadTestsFromTestCase(AppTests))
    runner = unittest.TextTestRunner(verbosity=2)
    runner.run(suite)

class AppTests(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        self.app = app.test_client()
        with app.app_context():
            db.create_all()
            seed_demo_data()

    def tearDown(self):
        with app.app_context():
            db.session.remove()
            db.drop_all()

    def test_index(self):
        rv = self.app.get('/')
        self.assertEqual(rv.status_code, 200)

    def test_login(self):
        rv = self.app.post('/login', data=dict(email='admin@example.com', password='admin123'), follow_redirects=True)
        self.assertIn(b'Logged in successfully', rv.data)

    def test_cart(self):
        with app.app_context():
            product = Product.query.first()
            if product:
                self.app.post('/login', data=dict(email='buyer@example.com', password='buyer123'))
                rv = self.app.post(f'/add_to_cart/{product.id}', data=dict(quantity=1), follow_redirects=True)
                self.assertIn(b'Added to cart', rv.data)

    def test_admin_access(self):
        self.app.post('/login', data=dict(email='admin@example.com', password='admin123'))
        rv = self.app.get('/admin')
        self.assertEqual(rv.status_code, 200)

# ---------- RUN (only when executed directly) ----------
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
