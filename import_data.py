from functools import wraps
from io import BytesIO

from flask import Flask, render_template, request, redirect, url_for, flash, session, send_file
import qrcode
from mysql.connector import Error

from config import SECRET_KEY, QR_FORM_URL
from db import get_connection, test_connection

app = Flask(__name__)
app.config['SECRET_KEY'] = SECRET_KEY

STATUS_LIST = ['Новая заявка', 'В процессе ремонта', 'Готова к выдаче']
MASTER_TYPES = ['Мастер']
ALLOWED_ADD_TYPES = ['Оператор', 'Менеджер']


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if 'user_id' not in session:
            flash('Сначала войдите в систему.')
            return redirect(url_for('login'))
        return view(*args, **kwargs)
    return wrapped


def role_required(*allowed_types):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if 'user_id' not in session:
                return redirect(url_for('login'))
            if session.get('role') not in allowed_types:
                flash('У вас нет доступа к этому действию.')
                return redirect(url_for('requests_list'))
            return view(*args, **kwargs)
        return wrapped
    return decorator


@app.context_processor
def inject_user():
    return {
        'current_role': session.get('role'),
        'current_fio': session.get('fio'),
        'status_list': STATUS_LIST,
    }


@app.route('/', methods=['GET', 'POST'])
def login():
    ok, message = test_connection()
    if not ok:
        return render_template('db_error.html', error_message=message)

    if request.method == 'POST':
        login_value = request.form.get('login', '').strip()
        password_value = request.form.get('password', '').strip()

        conn = get_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute('SELECT * FROM users WHERE login = %s', (login_value,))
        user = cur.fetchone()
        cur.close()
        conn.close()

        if user and str(user['password']) == password_value:
            session['user_id'] = user['userID']
            session['fio'] = user['fio']
            session['role'] = user['type']
            flash('Вход выполнен успешно.')
            return redirect(url_for('requests_list'))

        flash('Неверный логин или пароль.')

    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    flash('Вы вышли из системы.')
    return redirect(url_for('login'))


@app.route('/requests')
@login_required
def requests_list():
    search = request.args.get('search', '').strip()
    status = request.args.get('status', '').strip()

    query = '''
        SELECT r.*, m.fio AS master_name, c.fio AS client_name
        FROM requests r
        LEFT JOIN users m ON r.masterID = m.userID
        LEFT JOIN users c ON r.clientID = c.userID
        WHERE 1=1
    '''
    params = []

    if search:
        query += '''
            AND (
                CAST(r.requestID AS CHAR) LIKE %s OR
                r.homeTechType LIKE %s OR
                r.homeTechModel LIKE %s OR
                r.problemDescryption LIKE %s OR
                c.fio LIKE %s
            )
        '''
        pattern = f'%{search}%'
        params.extend([pattern] * 5)

    if status:
        query += ' AND r.requestStatus = %s'
        params.append(status)

    query += ' ORDER BY r.requestID DESC'

    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute(query, params)
    requests_data = cur.fetchall()
    cur.close()
    conn.close()

    return render_template(
        'requests.html',
        requests_data=requests_data,
        search=search,
        selected_status=status,
    )


@app.route('/request/add', methods=['GET', 'POST'])
@login_required
@role_required(*ALLOWED_ADD_TYPES)
def add_request():
    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT userID, fio FROM users WHERE type='Заказчик' ORDER BY fio")
    clients = cur.fetchall()
    cur.execute("SELECT userID, fio FROM users WHERE type='Мастер' ORDER BY fio")
    masters = cur.fetchall()

    if request.method == 'POST':
        form = request.form
        cur2 = conn.cursor()
        cur2.execute(
            '''
            INSERT INTO requests (
                startDate, homeTechType, homeTechModel,
                problemDescryption, requestStatus, completionDate,
                repairParts, masterID, clientID
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ''',
            (
                form.get('startDate'),
                form.get('homeTechType'),
                form.get('homeTechModel'),
                form.get('problemDescryption'),
                'Новая заявка',
                None,
                form.get('repairParts') or '',
                form.get('masterID') or None,
                form.get('clientID'),
            ),
        )
        conn.commit()
        cur2.close()
        cur.close()
        conn.close()
        flash('Заявка добавлена.')
        return redirect(url_for('requests_list'))

    cur.close()
    conn.close()
    return render_template('add_request.html', clients=clients, masters=masters)


@app.route('/request/<int:request_id>')
@login_required
def request_detail(request_id):
    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute(
        '''
        SELECT r.*, m.fio AS master_name, c.fio AS client_name, c.phone AS client_phone
        FROM requests r
        LEFT JOIN users m ON r.masterID = m.userID
        LEFT JOIN users c ON r.clientID = c.userID
        WHERE r.requestID = %s
        ''',
        (request_id,),
    )
    request_data = cur.fetchone()
    if not request_data:
        cur.close()
        conn.close()
        flash('Заявка не найдена.')
        return redirect(url_for('requests_list'))

    cur.execute(
        '''
        SELECT c.commentID, c.message, c.masterID, c.requestID, u.fio AS master_name
        FROM comments c
        JOIN users u ON c.masterID = u.userID
        WHERE c.requestID = %s
        ORDER BY c.commentID DESC
        ''',
        (request_id,),
    )
    comments = cur.fetchall()

    cur.execute("SELECT userID, fio FROM users WHERE type='Мастер' ORDER BY fio")
    masters = cur.fetchall()
    cur.execute("SELECT userID, fio FROM users WHERE type='Заказчик' ORDER BY fio")
    clients = cur.fetchall()
    cur.close()
    conn.close()
    return render_template('request_detail.html', request_data=request_data, comments=comments, masters=masters, clients=clients)


@app.route('/request/<int:request_id>/edit', methods=['POST'])
@login_required
@role_required('Оператор', 'Менеджер')
def edit_request(request_id):
    form = request.form
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        '''
        UPDATE requests
        SET startDate=%s,
            homeTechType=%s,
            homeTechModel=%s,
            problemDescryption=%s,
            clientID=%s
        WHERE requestID=%s
        ''',
        (
            form.get('startDate'),
            form.get('homeTechType'),
            form.get('homeTechModel'),
            form.get('problemDescryption'),
            form.get('clientID'),
            request_id,
        ),
    )
    conn.commit()
    cur.close()
    conn.close()
    flash('Данные заявки обновлены.')
    return redirect(url_for('request_detail', request_id=request_id))


@app.route('/request/<int:request_id>/assign-master', methods=['POST'])
@login_required
@role_required('Оператор', 'Менеджер')
def assign_master(request_id):
    master_id = request.form.get('master_id') or None
    conn = get_connection()
    cur = conn.cursor()
    cur.execute('UPDATE requests SET masterID=%s WHERE requestID=%s', (master_id, request_id))
    conn.commit()
    cur.close()
    conn.close()
    flash('Мастер назначен.')
    return redirect(url_for('request_detail', request_id=request_id))


@app.route('/request/<int:request_id>/status', methods=['POST'])
@login_required
def update_status(request_id):
    new_status = request.form.get('status')
    if new_status not in STATUS_LIST:
        flash('Некорректный статус.')
        return redirect(url_for('request_detail', request_id=request_id))

    conn = get_connection()
    cur = conn.cursor()
    if new_status == 'Готова к выдаче':
        cur.execute(
            'UPDATE requests SET requestStatus=%s, completionDate=CURDATE() WHERE requestID=%s',
            (new_status, request_id),
        )
    else:
        cur.execute(
            'UPDATE requests SET requestStatus=%s WHERE requestID=%s',
            (new_status, request_id),
        )
    conn.commit()
    cur.close()
    conn.close()
    flash('Статус обновлён.')
    return redirect(url_for('request_detail', request_id=request_id))


@app.route('/request/<int:request_id>/comment', methods=['POST'])
@login_required
@role_required('Мастер')
def add_comment(request_id):
    message = request.form.get('message', '').strip()
    repair_parts = request.form.get('repairParts', '').strip()
    if not message and not repair_parts:
        flash('Добавьте комментарий или укажите запчасти.')
        return redirect(url_for('request_detail', request_id=request_id))

    conn = get_connection()
    cur = conn.cursor()
    if message:
        cur.execute(
            'INSERT INTO comments (message, masterID, requestID) VALUES (%s, %s, %s)',
            (message, session['user_id'], request_id),
        )
    if repair_parts:
        cur.execute('UPDATE requests SET repairParts=%s WHERE requestID=%s', (repair_parts, request_id))
    conn.commit()
    cur.close()
    conn.close()
    flash('Информация по ремонту сохранена.')
    return redirect(url_for('request_detail', request_id=request_id))


@app.route('/request/<int:request_id>/qr')
@login_required
def generate_qr(request_id):
    qr = qrcode.make(QR_FORM_URL)
    buf = BytesIO()
    qr.save(buf, format='PNG')
    buf.seek(0)
    return send_file(buf, mimetype='image/png', download_name=f'request_{request_id}_qr.png')


@app.route('/stats')
@login_required
def stats():
    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT COUNT(*) AS total FROM requests WHERE requestStatus='Готова к выдаче'")
    completed_count = cur.fetchone()['total']

    cur.execute('''
        SELECT ROUND(AVG(DATEDIFF(completionDate, startDate)), 2) AS avg_days
        FROM requests
        WHERE completionDate IS NOT NULL
    ''')
    avg_days = cur.fetchone()['avg_days']

    cur.execute('''
        SELECT homeTechType, COUNT(*) AS total
        FROM requests
        GROUP BY homeTechType
        ORDER BY total DESC
    ''')
    by_type = cur.fetchall()

    cur.execute('''
        SELECT requestStatus, COUNT(*) AS total
        FROM requests
        GROUP BY requestStatus
        ORDER BY total DESC
    ''')
    by_status = cur.fetchall()
    cur.close()
    conn.close()
    return render_template('stats.html', completed_count=completed_count, avg_days=avg_days, by_type=by_type, by_status=by_status)


@app.errorhandler(Error)
def handle_db_error(error):
    return render_template('db_error.html', error_message=str(error)), 500


if __name__ == '__main__':
    app.run(debug=True)
