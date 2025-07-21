from flask import Blueprint, render_template, redirect, request, url_for, flash, session
from flask_login import login_user, logout_user, login_required
from werkzeug.security import check_password_hash  # ✅ THIS LINE
from static.auth.models import User  # Adjust as per your folder structure

auth = Blueprint('auth', __name__)

# ✅ Use auth.route instead of app.route
@auth.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        # Adjust this based on your actual User model logic
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password, password):
            login_user(user)
            session.permanent = True
            return redirect(url_for('home'))  # Update if home is inside a blueprint
        return "Invalid credentials", 401

    return render_template('login.html')

@auth.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('auth.login'))
