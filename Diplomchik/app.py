from flask import Flask, render_template, request, redirect, session, url_for, jsonify
import firebase_admin
from firebase_admin import credentials, db
from datetime import datetime
import random

app = Flask(__name__)
app.secret_key = "supersecretkey"  # для сессий

# -------------------- Firebase --------------------
cred = credentials.Certificate("serviceAccountKey.json")
firebase_admin.initialize_app(cred, {
    'databaseURL': 'https://coffee-to-go-812dd-default-rtdb.firebaseio.com/'
})

root_ref = db.reference("/coffee_shop")

# -------------------- Routes ----------------------
@app.route('/')
def index():
    menu = root_ref.child('menu').get() or {}
    return render_template('index.html', menu=menu)

# Логин
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        login = request.form['login']
        password = request.form['password']
        users = root_ref.child('users').get() or {}
        for uid, user in users.items():
            if user.get('login') == login and user.get('password') == password:
                session['user'] = uid
                session['role'] = user.get('role')
                return redirect(url_for('admin_menu'))
        return render_template('login.html', error="Неверный логин или пароль")
    return render_template('login.html')

# Просмотр и редактирование меню (админ) — теперь отдаём menu, orders_list, users_list
@app.route('/admin/menu', methods=['GET', 'POST'])
def admin_menu():
    if 'user' not in session or session.get('role') != 'admin':
        return redirect(url_for('login'))

    menu_ref = root_ref.child('menu')

    if request.method == 'POST':
        # Добавляем новый товар
        name = request.form.get('name', '').strip()
        price = int(request.form.get('price') or 0)
        category = request.form.get('category', '').strip()
        current_menu = menu_ref.get() or {}
        next_index = len(current_menu) + 1
        item_key = f"item_{next_index:03d}"
        menu_ref.child(item_key).set({
            'name': name,
            'price': price,
            'category': category,
            'available': True
        })
        return redirect(url_for('admin_menu'))

    menu = menu_ref.get() or {}
    # заказы и пользователи для вывода в админке
    orders = root_ref.child('orders').get() or {}
    users = root_ref.child('users').get() or {}

    # Преобразуем orders и users в списки удобные для шаблона
    orders_list = []
    for oid, odata in (orders.items() if isinstance(orders, dict) else []):
        orders_list.append({
            'id': oid,
            'items': odata.get('items', {}),
            'total': odata.get('total', 0),
            'status': odata.get('status', ''),
            'datetime': odata.get('datetime', '')
        })
    # сортируем по дате (если есть)
    orders_list.sort(key=lambda x: x.get('datetime') or '', reverse=True)

    users_list = []
    for uid, udata in (users.items() if isinstance(users, dict) else []):
        users_list.append({
            'id': uid,
            'name': udata.get('name') or udata.get('login') or '',
            'email': udata.get('email', ''),
            'phone': udata.get('phone', ''),
            'role': udata.get('role', '')
        })

    return render_template('admin_menu.html', menu=menu, orders=orders_list, users=users_list)

# Просмотр заказов (отдельный роут, если нужно)
@app.route('/admin/orders')
def admin_orders():
    if 'user' not in session or session.get('role') != 'admin':
        return redirect(url_for('login'))
    orders = root_ref.child('orders').get() or {}
    menu = root_ref.child('menu').get() or {}
    orders_list = []
    for oid, odata in (orders.items() if isinstance(orders, dict) else []):
        orders_list.append({
            'id': oid,
            'items': odata.get('items', {}),
            'total': odata.get('total', 0),
            'status': odata.get('status', ''),
            'datetime': odata.get('datetime', '')
        })
    orders_list.sort(key=lambda x: x.get('datetime') or '', reverse=True)
    return render_template('admin_orders.html', orders=orders_list, menu=menu)

# Изменение статуса заказа (админ)
@app.route('/admin/orders/<order_id>/status', methods=['POST'])
def change_status(order_id):
    if 'user' not in session or session.get('role') != 'admin':
        return redirect(url_for('login'))
    new_status = request.form['status']
    root_ref.child('orders').child(order_id).update({'status': new_status})
    return redirect(url_for('admin_orders'))

# Удаление товара (админ)
@app.route('/admin/menu/<item_id>/delete', methods=['POST'])
def delete_item(item_id):
    if 'user' not in session or session.get('role') != 'admin':
        return redirect(url_for('login'))
    root_ref.child('menu').child(item_id).delete()
    return redirect(url_for('admin_menu'))

# Редактирование товара (админ)
@app.route('/admin/edit/<item_id>', methods=['GET', 'POST'])
def edit_item(item_id):
    if 'user' not in session or session.get('role') != 'admin':
        return redirect(url_for('login'))
    menu_ref = root_ref.child('menu')
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        category = request.form.get('category', '').strip()
        price = float(request.form.get('price') or 0)
        menu_ref.child(item_id).update({
            'name': name,
            'category': category,
            'price': price
        })
        return redirect(url_for('admin_menu'))
    item = menu_ref.child(item_id).get() or {}
    return render_template('edit_item.html', item=item, item_id=item_id)

# Создание заказа клиентом
@app.route('/create_order', methods=['POST'])
def create_order():
    data = request.get_json()  # получаем корзину в виде JSON
    if not data:
        return jsonify({'ok': False, 'message': "Корзина пуста"}), 400

    # считаем total и нормализуем items
    items = {}
    total = 0
    for key, v in data.items():
        name = v.get('name')
        price = float(v.get('price', 0))
        qty = int(v.get('quantity', 0))
        items[key] = {'name': name, 'price': price, 'quantity': qty}
        total += price * qty

    # Генерация уникального order_id
    order_id = f"order_{random.randint(1000, 9999)}"

    # Сохранение в Firebase
    root_ref.child('orders').child(order_id).set({
        'items': items,
        'total': total,
        'status': 'new',
        'datetime': datetime.now().strftime("%Y-%m-%d %H:%M")
    })

    # Возвращаем JSON с id и сообщением (frontend покажет красивый toast)
    return jsonify({'ok': True, 'order_id': order_id, 'message': f"Ваш заказ №{order_id} успешно создан!"})

# Логин баристы
@app.route('/login_barista', methods=['GET', 'POST'])
def login_barista():
    if request.method == 'POST':
        login = request.form['login']
        password = request.form['password']
        users = root_ref.child('users').get() or {}
        for uid, user in users.items():
            if user.get('login') == login and user.get('password') == password and user.get('role') == 'barista':
                session['user'] = uid
                session['role'] = 'barista'
                return redirect(url_for('barista_orders'))
        return render_template('login_barista.html', error="Неверный логин или пароль")
    return render_template('login_barista.html')

@app.route('/barista/orders')
def barista_orders():
    # проверка роли
    if 'user' not in session or session.get('role') != 'barista':
        return redirect('/login_barista')

    orders = root_ref.child("orders").get() or {}
    orders_list = []
    for oid, odata in orders.items():
        orders_list.append({
            "id": oid,
            "items": odata.get("items", {}),
            "total": odata.get("total", 0),
            "status": odata.get("status", ""),
            "datetime": odata.get("datetime", "")
        })

    orders_list.sort(key=lambda x: x.get("datetime") or "", reverse=True)

    return render_template("barista_orders.html", orders=orders_list)
# Панель баристы — преобразуем orders в список, отсортированный по datetime
@app.route('/api/barista/orders')
def api_barista_orders():
    # проверка роли
    if 'user' not in session or session.get('role') != 'barista':
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401

    orders = root_ref.child('orders').get() or {}
    orders_list = []
    for oid, odata in (orders.items() if isinstance(orders, dict) else []):
        orders_list.append({
            'id': oid,
            'items': odata.get('items', {}),
            'total': odata.get('total', 0),
            'status': odata.get('status', ''),
            'datetime': odata.get('datetime', '')
        })
    # сортируем по datetime при наличии
    orders_list.sort(key=lambda x: x.get('datetime') or '', reverse=True)
    return jsonify({'ok': True, 'orders': orders_list})

# Обновление статуса заказа баристой
@app.route('/barista/orders/<order_id>/status', methods=['POST'])
def barista_change_status(order_id):
    if 'user' not in session or session.get('role') != 'barista':
        return redirect(url_for('login_barista'))
    new_status = request.form.get('status')
    root_ref.child('orders').child(order_id).update({'status': new_status})
    return redirect(url_for('barista_orders'))

# Удаление заказа (админ) — опционально
@app.route('/admin/orders/<order_id>/delete', methods=['POST'])
def admin_delete_order(order_id):
    if 'user' not in session or session.get('role') != 'admin':
        return redirect(url_for('login'))
    root_ref.child('orders').child(order_id).delete()
    return redirect(url_for('admin_orders'))

# Выход
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

# -------------------- Run -------------------------
if __name__ == '__main__':
    app.run(debug=True)
