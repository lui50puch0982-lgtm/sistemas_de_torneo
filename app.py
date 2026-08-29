import os
import re
import sqlite3
import itertools
import random
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'clave_secreta_torneo_dev_default')

# ==========================================
# CONFIGURACIÓN DE BASE DE DATOS (PERSISTENCIA)
# ==========================================
# Ruta base del proyecto
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# DATABASE_PATH: En Render será '/data/database.sqlite' o '/data/torneo.db'
# En desarrollo local por defecto se usará 'torneo.db' en el directorio del proyecto
DATABASE_PATH = os.environ.get('DATABASE_PATH', os.path.join(BASE_DIR, 'torneo.db'))

# Asegurar que el directorio de la base de datos exista (evita error 'unable to open database file')
_db_dir = os.path.dirname(os.path.abspath(DATABASE_PATH))
if _db_dir:
    os.makedirs(_db_dir, exist_ok=True)

# ==========================================
# DECORADORES DE SEGURIDAD (ROLES Y SESIÓN)
# ==========================================

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Debes iniciar sesión para acceder.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Debes iniciar sesión para acceder.', 'warning')
            return redirect(url_for('login'))
        if session.get('rol') != 'admin':
            flash('Acceso denegado: Se requieren permisos de administrador.', 'danger')
            return redirect(url_for('perfil_atleta'))
        return f(*args, **kwargs)
    return decorated_function

# ==========================================
# BASE DE DATOS Y CONFIGURACIÓN INICIAL
# ==========================================

def get_db_connection():
    # Asegurar que el directorio exista en tiempo de ejecución
    _dir = os.path.dirname(os.path.abspath(DATABASE_PATH))
    if _dir:
        os.makedirs(_dir, exist_ok=True)

    conn = sqlite3.connect(DATABASE_PATH, timeout=15.0)
    conn.row_factory = sqlite3.Row

    # Optimizaciones de concurrencia e integridad para producción
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA busy_timeout = 5000;")
    conn.execute("PRAGMA synchronous = NORMAL;")

    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Tabla Usuarios
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            rol TEXT NOT NULL
        )
    ''')
    
    # Tabla Atletas
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS atletas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario_id INTEGER,
            nombre_completo TEXT NOT NULL,
            ci TEXT NOT NULL,
            departamento TEXT NOT NULL,
            club TEXT NOT NULL,
            modalidad TEXT NOT NULL,
            categoria_peso TEXT NOT NULL,
            peso_inscripcion REAL NOT NULL,
            peso_oficial REAL DEFAULT 0,
            dorsal INTEGER DEFAULT NULL,
            estado TEXT DEFAULT 'PENDIENTE',
            FOREIGN KEY (usuario_id) REFERENCES usuarios (id)
        )
    ''')
    
    # Tabla Combates
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS combates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tapiz TEXT DEFAULT 'Tapiz A',
            numero_combate INTEGER NOT NULL,
            ronda INTEGER DEFAULT 1,
            grupo TEXT DEFAULT 'Fase Unica',
            fase TEXT DEFAULT 'Grupos',
            modalidad TEXT NOT NULL,
            categoria_peso TEXT NOT NULL,
            atleta_rojo_id INTEGER,
            atleta_azul_id INTEGER,
            puntos_rojo INTEGER DEFAULT 0,
            puntos_azul INTEGER DEFAULT 0,
            ganador_id INTEGER DEFAULT NULL,
            tipo_victoria TEXT DEFAULT NULL,
            estado TEXT DEFAULT 'PROGRAMADO',
            arbitro TEXT DEFAULT '',
            juez TEXT DEFAULT '',
            jefe_tapiz TEXT DEFAULT '',
            FOREIGN KEY (atleta_rojo_id) REFERENCES atletas (id),
            FOREIGN KEY (atleta_azul_id) REFERENCES atletas (id),
            FOREIGN KEY (ganador_id) REFERENCES atletas (id)
        )
    ''')
    
    # Crear usuario admin por defecto
    cursor.execute("SELECT * FROM usuarios WHERE username = 'admin'")
    if not cursor.fetchone():
        cursor.execute("INSERT INTO usuarios (username, password, rol) VALUES ('admin', 'admin123', 'admin')")
        
    conn.commit()
    conn.close()

with app.app_context():
    init_db()

# ==========================================
# RUTAS PÚBLICAS Y AUTENTICACIÓN
# ==========================================

@app.route('/')
@app.route('/index')
@app.route('/index.html')
def index():
    # Si el usuario ya está autenticado, enviarlo a su panel correspondiente
    if 'user_id' in session:
        if session.get('rol') == 'admin':
            return redirect(url_for('admin_dashboard'))
        else:
            return redirect(url_for('perfil_atleta'))
    # Si no ha iniciado sesión, redirigir a la pantalla principal de Login
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
@app.route('/login.html', methods=['GET', 'POST'])
def login():
    # Si el usuario ya tiene sesión iniciada, redirigir según su rol
    if request.method == 'GET' and 'user_id' in session:
        if session.get('rol') == 'admin':
            return redirect(url_for('admin_dashboard'))
        else:
            return redirect(url_for('perfil_atleta'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        
        conn = get_db_connection()
        user = conn.execute('SELECT * FROM usuarios WHERE LOWER(username) = LOWER(?) AND password = ?', (username, password)).fetchone()
        conn.close()
        
        if user:
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['rol'] = user['rol']
            if user['rol'] == 'admin':
                return redirect(url_for('admin_dashboard'))
            else:
                return redirect(url_for('perfil_atleta'))
        flash('Credenciales incorrectas. Por favor verifica tu usuario y contraseña.', 'danger')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Has cerrado sesión correctamente.', 'info')
    return redirect(url_for('login'))

@app.route('/registro_atleta', methods=['GET', 'POST'])
@app.route('/registro', methods=['GET', 'POST'])
@app.route('/registro.html', methods=['GET', 'POST'])
@app.route('/registro_atleta.html', methods=['GET', 'POST'])
def registro_usuario():
    if request.method == 'POST':
        nombre_completo = request.form.get('nombre_completo', '').strip()
        ci = request.form.get('ci', '').strip()
        departamento = request.form.get('departamento', '').strip()
        club = request.form.get('club', '').strip()
        modalidad = request.form.get('modalidad', '').strip()
        categoria_peso = request.form.get('categoria_peso', '').strip()
        peso_raw = request.form.get('peso_inscripcion', '').strip()
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        password_confirm = request.form.get('password_confirm', '')

        # Validaciones de campos requeridos
        if not all([nombre_completo, ci, departamento, club, modalidad, categoria_peso, peso_raw, username, password]):
            flash('Por favor completa todos los campos del formulario.', 'danger')
            return render_template('registro.html', form_data=request.form)

        # Validación de Nombre Completo
        if len(nombre_completo) < 3:
            flash('El nombre completo debe contener al menos 3 caracteres.', 'danger')
            return render_template('registro.html', form_data=request.form)

        # Validación de CI / Documento
        if len(ci) < 3:
            flash('El número de C.I. / Documento de Identidad debe tener al menos 3 caracteres.', 'danger')
            return render_template('registro.html', form_data=request.form)

        # Validación de Peso
        try:
            peso_inscripcion = float(peso_raw)
            if peso_inscripcion < 20 or peso_inscripcion > 250:
                flash('El peso debe estar entre 20 kg y 250 kg.', 'danger')
                return render_template('registro.html', form_data=request.form)
        except (ValueError, TypeError):
            flash('El peso de inscripción debe ser un número válido (ejemplo: 74.5).', 'danger')
            return render_template('registro.html', form_data=request.form)

        # Validación de Nombre de Usuario
        if len(username) < 3:
            flash('El nombre de usuario debe tener al menos 3 caracteres.', 'danger')
            return render_template('registro.html', form_data=request.form)

        if not re.match(r'^[a-zA-Z0-9_.-]+$', username):
            flash('El nombre de usuario solo puede contener letras, números, puntos (.) o guiones (_-).', 'danger')
            return render_template('registro.html', form_data=request.form)

        # Validación de Contraseña
        if len(password) < 4:
            flash('La contraseña debe tener al menos 4 caracteres.', 'danger')
            return render_template('registro.html', form_data=request.form)

        if password_confirm and password != password_confirm:
            flash('Las contraseñas ingresadas no coinciden.', 'danger')
            return render_template('registro.html', form_data=request.form)

        conn = get_db_connection()
        cursor = conn.cursor()

        # Verificar si el usuario ya existe
        usuario_existente = cursor.execute('SELECT id FROM usuarios WHERE LOWER(username) = LOWER(?)', (username,)).fetchone()
        if usuario_existente:
            conn.close()
            flash(f'El nombre de usuario "{username}" ya está en uso. Por favor elige otro.', 'danger')
            return render_template('registro.html', form_data=request.form)

        try:
            cursor.execute('INSERT INTO usuarios (username, password, rol) VALUES (?, ?, ?)',
                           (username, password, 'atleta'))
            usuario_id = cursor.lastrowid
            
            cursor.execute('''
                INSERT INTO atletas (usuario_id, nombre_completo, ci, departamento, club, modalidad, categoria_peso, peso_inscripcion)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (usuario_id, nombre_completo, ci, departamento, club, modalidad, categoria_peso, peso_inscripcion))
            
            conn.commit()
            flash('¡Pre-inscripción enviada con éxito! Ya puedes iniciar sesión con tu cuenta.', 'success')
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            conn.rollback()
            flash('El nombre de usuario o registro ya existe en el sistema.', 'danger')
            return render_template('registro.html', form_data=request.form)
        except Exception as e:
            conn.rollback()
            flash(f'Error al procesar el registro: {str(e)}', 'danger')
            return render_template('registro.html', form_data=request.form)
        finally:
            conn.close()
            
    return render_template('registro.html', form_data={})

@app.route('/tabla_posiciones')
def tabla_posiciones():
    conn = get_db_connection()
    categorias = conn.execute('''
        SELECT DISTINCT modalidad, categoria_peso 
        FROM atletas 
        WHERE LOWER(estado) IN ('acreditado', 'confirmado')
        ORDER BY modalidad, categoria_peso
    ''').fetchall()
    
    categoria_sel = request.args.get('categoria', '')
    posiciones = []
    
    if categoria_sel and ' - ' in categoria_sel:
        modalidad, peso = [x.strip() for x in categoria_sel.split(' - ')]
        
        atletas = conn.execute('''
            SELECT id, nombre_completo, club, dorsal 
            FROM atletas 
            WHERE modalidad = ? AND categoria_peso = ? AND LOWER(estado) IN ('acreditado', 'confirmado')
        ''', (modalidad, peso)).fetchall()
        
        combates = conn.execute('''
            SELECT atleta_rojo_id, atleta_azul_id, puntos_rojo, puntos_azul, ganador_id 
            FROM combates 
            WHERE modalidad = ? AND categoria_peso = ? AND estado = 'FINALIZADO'
        ''', (modalidad, peso)).fetchall()
        
        stats = {}
        for a in atletas:
            stats[a['id']] = {
                'dorsal': a['dorsal'],
                'nombre': a['nombre_completo'],
                'club': a['club'],
                'victorias': 0,
                'derrotas': 0,
                'puntos_favor': 0,
                'puntos_contra': 0,
                'diferencia': 0
            }
            
        for c in combates:
            rojo_id, azul_id = c['atleta_rojo_id'], c['atleta_azul_id']
            p_rojo, p_azul = c['puntos_rojo'] or 0, c['puntos_azul'] or 0
            ganador = c['ganador_id']
            
            if rojo_id in stats:
                stats[rojo_id]['puntos_favor'] += p_rojo
                stats[rojo_id]['puntos_contra'] += p_azul
                if ganador == rojo_id:
                    stats[rojo_id]['victorias'] += 1
                elif ganador is not None and ganador != rojo_id:
                    stats[rojo_id]['derrotas'] += 1

            if azul_id in stats:
                stats[azul_id]['puntos_favor'] += p_azul
                stats[azul_id]['puntos_contra'] += p_rojo
                if ganador == azul_id:
                    stats[azul_id]['victorias'] += 1
                elif ganador is not None and ganador != azul_id:
                    stats[azul_id]['derrotas'] += 1

        for a_id in stats:
            stats[a_id]['diferencia'] = stats[a_id]['puntos_favor'] - stats[a_id]['puntos_contra']
            posiciones.append(stats[a_id])

        posiciones.sort(key=lambda x: (x['victorias'], x['diferencia'], x['puntos_favor']), reverse=True)
        
    conn.close()
    return render_template('publico/posiciones.html', 
                           categorias=categorias, 
                           categoria_sel=categoria_sel, 
                           posiciones=posiciones)

@app.route('/api/posiciones')
def api_posiciones():
    categoria_sel = request.args.get('categoria', '')
    if not categoria_sel or ' - ' not in categoria_sel:
        return jsonify([])
        
    modalidad, peso = [x.strip() for x in categoria_sel.split(' - ')]
    conn = get_db_connection()
    
    atletas = conn.execute('''
        SELECT id, nombre_completo, club, dorsal 
        FROM atletas 
        WHERE modalidad = ? AND categoria_peso = ? AND LOWER(estado) IN ('acreditado', 'confirmado')
    ''', (modalidad, peso)).fetchall()
    
    combates = conn.execute('''
        SELECT atleta_rojo_id, atleta_azul_id, puntos_rojo, puntos_azul, ganador_id 
        FROM combates 
        WHERE modalidad = ? AND categoria_peso = ? AND estado = 'FINALIZADO'
    ''', (modalidad, peso)).fetchall()
    
    stats = {}
    for a in atletas:
        stats[a['id']] = {
            'dorsal': a['dorsal'],
            'nombre': a['nombre_completo'],
            'club': a['club'],
            'victorias': 0,
            'derrotas': 0,
            'puntos_favor': 0,
            'puntos_contra': 0,
            'diferencia': 0
        }
        
    for c in combates:
        rojo_id, azul_id = c['atleta_rojo_id'], c['atleta_azul_id']
        p_rojo, p_azul = c['puntos_rojo'] or 0, c['puntos_azul'] or 0
        ganador = c['ganador_id']
        
        if rojo_id in stats:
            stats[rojo_id]['puntos_favor'] += p_rojo
            stats[rojo_id]['puntos_contra'] += p_azul
            if ganador == rojo_id:
                stats[rojo_id]['victorias'] += 1
            elif ganador is not None and ganador != rojo_id:
                stats[rojo_id]['derrotas'] += 1

        if azul_id in stats:
            stats[azul_id]['puntos_favor'] += p_azul
            stats[azul_id]['puntos_contra'] += p_rojo
            if ganador == azul_id:
                stats[azul_id]['victorias'] += 1
            elif ganador is not None and ganador != azul_id:
                stats[azul_id]['derrotas'] += 1

    posiciones = []
    for a_id in stats:
        stats[a_id]['diferencia'] = stats[a_id]['puntos_favor'] - stats[a_id]['puntos_contra']
        posiciones.append(stats[a_id])

    posiciones.sort(key=lambda x: (x['victorias'], x['diferencia'], x['puntos_favor']), reverse=True)
    conn.close()
    
    return jsonify(posiciones)

# ==========================================
# RUTAS PROTEGIDAS - ROL ATLETA
# ==========================================

@app.route('/atleta/perfil')
@login_required
def perfil_atleta():
    conn = get_db_connection()
    atleta = conn.execute('SELECT * FROM atletas WHERE usuario_id = ?', (session['user_id'],)).fetchone()
    combates = []
    if atleta:
        combates = conn.execute('''
            SELECT c.*, 
                   r.nombre_completo AS rojo_nombre, a.nombre_completo AS azul_nombre,
                   g.nombre_completo AS ganador_nombre
            FROM combates c
            LEFT JOIN atletas r ON c.atleta_rojo_id = r.id
            LEFT JOIN atletas a ON c.atleta_azul_id = a.id
            LEFT JOIN atletas g ON c.ganador_id = g.id
            WHERE c.atleta_rojo_id = ? OR c.atleta_azul_id = ?
            ORDER BY c.ronda ASC
        ''', (atleta['id'], atleta['id'])).fetchall()
    conn.close()
    return render_template('atleta/perfil.html', atleta=atleta, combates=combates)

# ==========================================
# RUTAS PROTEGIDAS - ROL ADMINISTRADOR
# ==========================================

@app.route('/admin/dashboard')
@admin_required
def admin_dashboard():
    conn = get_db_connection()
    atletas = conn.execute("SELECT * FROM atletas WHERE LOWER(estado) IN ('acreditado', 'confirmado')").fetchall()
    conn.close()
    return render_template('administrador/dashboard.html', atletas=atletas)

@app.route('/admin/acreditacion')
@admin_required
def admin_acreditacion():
    conn = get_db_connection()
    pendientes = conn.execute("SELECT * FROM atletas WHERE LOWER(estado) = 'pendiente'").fetchall()
    acreditados = conn.execute("SELECT * FROM atletas WHERE LOWER(estado) IN ('acreditado', 'confirmado')").fetchall()
    conn.close()
    return render_template('administrador/acreditacion.html', pendientes=pendientes, acreditados=acreditados)

@app.route('/admin/acreditar_atleta/<int:atleta_id>', methods=['POST'])
@admin_required
def acreditar_atleta(atleta_id):
    accion = request.form.get('accion')
    conn = get_db_connection()
    
    if accion == 'aprobar':
        atleta = conn.execute("SELECT dorsal FROM atletas WHERE id = ?", (atleta_id,)).fetchone()
        if atleta and not atleta['dorsal']:
            ultimo_dorsal = conn.execute("SELECT MAX(dorsal) FROM atletas WHERE dorsal IS NOT NULL").fetchone()[0]
            nuevo_dorsal = (ultimo_dorsal + 1) if ultimo_dorsal else 101
            conn.execute("UPDATE atletas SET estado = 'ACREDITADO', dorsal = ? WHERE id = ?", (nuevo_dorsal, atleta_id))
        else:
            conn.execute("UPDATE atletas SET estado = 'ACREDITADO' WHERE id = ?", (atleta_id,))
        flash('Atleta acreditado exitosamente.', 'success')
    elif accion == 'rechazar':
        conn.execute("UPDATE atletas SET estado = 'RECHAZADO' WHERE id = ?", (atleta_id,))
        flash('Atleta rechazado.', 'warning')
        
    conn.commit()
    conn.close()
    return redirect(url_for('admin_acreditacion'))

@app.route('/admin/pesaje', methods=['POST'])
@admin_required
def guardar_pesaje():
    atleta_id = request.form['atleta_id']
    peso_oficial = float(request.form['peso_oficial'])
    dorsal_form = request.form.get('dorsal', '').strip()
    
    conn = get_db_connection()
    atleta = conn.execute("SELECT dorsal FROM atletas WHERE id = ?", (atleta_id,)).fetchone()
    
    if dorsal_form and dorsal_form.isdigit():
        dorsal_final = int(dorsal_form)
    elif atleta and atleta['dorsal']:
        dorsal_final = atleta['dorsal']
    else:
        ultimo_dorsal = conn.execute("SELECT MAX(dorsal) FROM atletas WHERE dorsal IS NOT NULL").fetchone()[0]
        dorsal_final = (ultimo_dorsal + 1) if ultimo_dorsal else 101

    conn.execute('''
        UPDATE atletas 
        SET peso_oficial = ?, dorsal = ?, estado = 'CONFIRMADO' 
        WHERE id = ?
    ''', (peso_oficial, dorsal_final, atleta_id))
    
    conn.commit()
    conn.close()
    flash('Pesaje y dorsal registrados correctamente.', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/sorteo', methods=['GET'])
@admin_required
def admin_sorteo():
    conn = get_db_connection()
    categorias = conn.execute('''
        SELECT DISTINCT modalidad, categoria_peso 
        FROM atletas 
        WHERE LOWER(estado) IN ('acreditado', 'confirmado')
        ORDER BY modalidad, categoria_peso
    ''').fetchall()
    
    categoria_sel = request.args.get('categoria', '')
    atletas = []
    combates = []
    perdedores = []
    ronda_actual = 1
    ronda_completa = False
    
    if categoria_sel and ' - ' in categoria_sel:
        modalidad, peso = [x.strip() for x in categoria_sel.split(' - ')]
        
        atletas = conn.execute('''
            SELECT * FROM atletas 
            WHERE modalidad = ? AND categoria_peso = ? AND LOWER(estado) IN ('acreditado', 'confirmado')
        ''', (modalidad, peso)).fetchall()
        
        combates = conn.execute('''
            SELECT c.*, 
                   r.nombre_completo AS rojo_nombre, r.dorsal AS rojo_dorsal, r.club AS rojo_club,
                   a.nombre_completo AS azul_nombre, a.dorsal AS azul_dorsal, a.club AS azul_club,
                   g.nombre_completo AS ganador_nombre
            FROM combates c
            LEFT JOIN atletas r ON c.atleta_rojo_id = r.id
            LEFT JOIN atletas a ON c.atleta_azul_id = a.id
            LEFT JOIN atletas g ON c.ganador_id = g.id
            WHERE c.modalidad = ? AND c.categoria_peso = ?
            ORDER BY c.ronda ASC, c.numero_combate ASC
        ''', (modalidad, peso)).fetchall()

        ronda_max = conn.execute('''
            SELECT MAX(ronda) FROM combates WHERE modalidad = ? AND categoria_peso = ?
        ''', (modalidad, peso)).fetchone()[0]
        
        if ronda_max:
            ronda_actual = ronda_max
            pendientes = conn.execute('''
                SELECT COUNT(*) FROM combates 
                WHERE modalidad = ? AND categoria_peso = ? AND ronda = ? AND estado != 'FINALIZADO'
            ''', (modalidad, peso, ronda_actual)).fetchone()[0]
            ronda_completa = (pendientes == 0)

        perdedores = conn.execute('''
            SELECT DISTINCT a.id, a.nombre_completo, a.club, c.ronda
            FROM combates c
            JOIN atletas a ON (
                (a.id = c.atleta_rojo_id AND a.id != c.ganador_id) OR
                (a.id = c.atleta_azul_id AND a.id != c.ganador_id)
            )
            WHERE c.modalidad = ? AND c.categoria_peso = ? AND c.estado = 'FINALIZADO' AND c.atleta_azul_id IS NOT NULL
            ORDER BY c.ronda DESC
        ''', (modalidad, peso)).fetchall()

    else:
        combates = conn.execute('''
            SELECT c.*, 
                   r.nombre_completo AS rojo_nombre, r.dorsal AS rojo_dorsal, r.club AS rojo_club,
                   a.nombre_completo AS azul_nombre, a.dorsal AS azul_dorsal, a.club AS azul_club,
                   g.nombre_completo AS ganador_nombre
            FROM combates c
            LEFT JOIN atletas r ON c.atleta_rojo_id = r.id
            LEFT JOIN atletas a ON c.atleta_azul_id = a.id
            LEFT JOIN atletas g ON c.ganador_id = g.id
            ORDER BY c.ronda ASC, c.numero_combate ASC
        ''').fetchall()
    
    conn.close()
    return render_template('administrador/sorteo.html', 
                           categorias=categorias, 
                           categoria_sel=categoria_sel, 
                           atletas=atletas, 
                           combates=combates,
                           perdedores=perdedores,
                           ronda_actual=ronda_actual,
                           ronda_completa=ronda_completa)

@app.route('/admin/generar_sorteo', methods=['POST'])
@admin_required
def generar_sorteo():
    categoria_sel = request.form.get('categoria')
    tapiz = request.form.get('tapiz', 'Tapiz A')
    
    if not categoria_sel or ' - ' not in categoria_sel:
        flash('Selecciona una categoría válida.', 'warning')
        return redirect(url_for('admin_sorteo'))
        
    modalidad, peso = [x.strip() for x in categoria_sel.split(' - ')]
    
    conn = get_db_connection()
    atletas = conn.execute('''
        SELECT id FROM atletas 
        WHERE modalidad = ? AND categoria_peso = ? AND LOWER(estado) IN ('acreditado', 'confirmado')
    ''', (modalidad, peso)).fetchall()
    
    lista_ids = [a['id'] for a in atletas]
    n_atletas = len(lista_ids)
    
    if n_atletas < 2:
        flash('Se requieren al menos 2 atletas acreditados/confirmados.', 'warning')
        conn.close()
        return redirect(url_for('admin_sorteo', categoria=categoria_sel))
        
    conn.execute('DELETE FROM combates WHERE modalidad = ? AND categoria_peso = ?', (modalidad, peso))
    ultimo_num = conn.execute("SELECT MAX(numero_combate) FROM combates").fetchone()[0] or 0

    if 2 <= n_atletas <= 5:
        _generar_round_robin(lista_ids, modalidad, peso, tapiz, conn, ultimo_num)
        mensaje = f'Sistema Round Robin generado ({n_atletas} atletas).'
    elif 6 <= n_atletas <= 7:
        _generar_sistema_nordico(lista_ids, modalidad, peso, tapiz, conn, ultimo_num)
        mensaje = f'Sistema Nórdico de Grupos generado ({n_atletas} atletas).'
    else:
        _generar_eliminatoria_directa(lista_ids, modalidad, peso, tapiz, conn, ultimo_num)
        mensaje = f'Eliminación directa generada ({n_atletas} atletas).'
        
    conn.commit()
    conn.close()
    flash(mensaje, 'success')
    return redirect(url_for('admin_sorteo', categoria=categoria_sel))

@app.route('/admin/procesar_siguiente_ronda', methods=['POST'])
@admin_required
def procesar_siguiente_ronda():
    categoria_sel = request.form.get('categoria')
    if not categoria_sel or ' - ' not in categoria_sel:
        flash('Categoría inválida.', 'danger')
        return redirect(url_for('admin_sorteo'))
        
    modalidad, peso = [x.strip() for x in categoria_sel.split(' - ')]
    conn = get_db_connection()

    ronda_actual = conn.execute('''
        SELECT MAX(ronda) FROM combates WHERE modalidad = ? AND categoria_peso = ?
    ''', (modalidad, peso)).fetchone()[0] or 1

    pendientes = conn.execute('''
        SELECT COUNT(*) FROM combates 
        WHERE modalidad = ? AND categoria_peso = ? AND ronda = ? AND estado != 'FINALIZADO'
    ''', (modalidad, peso, ronda_actual)).fetchone()[0]

    if pendientes > 0:
        flash(f'Aún hay {pendientes} combates pendientes en la Ronda {ronda_actual}.', 'danger')
        conn.close()
        return redirect(url_for('admin_sorteo', categoria=categoria_sel))

    ganadores = conn.execute('''
        SELECT DISTINCT ganador_id FROM combates 
        WHERE modalidad = ? AND categoria_peso = ? AND ronda = ? AND ganador_id IS NOT NULL
    ''', (modalidad, peso, ronda_actual)).fetchall()

    lista_ganadores = [g['ganador_id'] for g in ganadores]

    if len(lista_ganadores) < 2:
        flash('No hay suficientes ganadores para generar una nueva sub-llave.', 'warning')
        conn.close()
        return redirect(url_for('admin_sorteo', categoria=categoria_sel))

    random.shuffle(lista_ganadores)

    siguiente_ronda = ronda_actual + 1
    ultimo_num = conn.execute("SELECT MAX(numero_combate) FROM combates").fetchone()[0] or 0
    tapiz = request.form.get('tapiz', 'Tapiz A')
    num_combate = ultimo_num + 1

    fase_nombre = f"Sub-llave Ronda {siguiente_ronda}" if len(lista_ganadores) > 2 else "Gran Final"

    for i in range(0, len(lista_ganadores), 2):
        rojo = lista_ganadores[i]
        azul = lista_ganadores[i+1] if (i+1) < len(lista_ganadores) else None

        if azul is None:
            conn.execute('''
                INSERT INTO combates (tapiz, numero_combate, ronda, grupo, fase, modalidad, categoria_peso, atleta_rojo_id, atleta_azul_id, ganador_id, tipo_victoria, estado)
                VALUES (?, ?, ?, 'Sub-llave Ganadores', ?, ?, ?, ?, NULL, ?, 'Pase Directo (Bye)', 'FINALIZADO')
            ''', (tapiz, num_combate, siguiente_ronda, fase_nombre, modalidad, peso, rojo, rojo))
        else:
            conn.execute('''
                INSERT INTO combates (tapiz, numero_combate, ronda, grupo, fase, modalidad, categoria_peso, atleta_rojo_id, atleta_azul_id)
                VALUES (?, ?, ?, 'Sub-llave Ganadores', ?, ?, ?, ?, ?)
            ''', (tapiz, num_combate, siguiente_ronda, fase_nombre, modalidad, peso, rojo, azul))

        num_combate += 1

    conn.commit()
    conn.close()
    flash(f'¡Ganadores filtrados! Sub-llave de la Ronda {siguiente_ronda} sorteada con éxito.', 'success')
    return redirect(url_for('admin_sorteo', categoria=categoria_sel))

@app.route('/admin/limpiar_combates', methods=['POST'])
@admin_required
def limpiar_combates():
    categoria_sel = request.form.get('categoria')
    
    conn = get_db_connection()
    if categoria_sel and ' - ' in categoria_sel:
        modalidad, peso = [x.strip() for x in categoria_sel.split(' - ')]
        conn.execute('DELETE FROM combates WHERE modalidad = ? AND categoria_peso = ?', (modalidad, peso))
        flash(f'Se eliminaron los combates de {categoria_sel}.', 'success')
    else:
        conn.execute('DELETE FROM combates')
        flash('Se han eliminado todos los combates.', 'warning')
        
    conn.commit()
    conn.close()
    return redirect(url_for('admin_sorteo', categoria=categoria_sel if categoria_sel else ''))

@app.route('/admin/combate/<int:combate_id>', methods=['GET', 'POST'])
@admin_required
def mesa_control(combate_id):
    conn = get_db_connection()
    
    if request.method == 'POST':
        puntos_rojo = int(request.form.get('puntos_rojo', 0))
        puntos_azul = int(request.form.get('puntos_azul', 0))
        ganador_id = request.form.get('ganador_id')
        forma_victoria = request.form.get('forma_victoria')
        accion = request.form.get('accion')
        
        arbitro = request.form.get('arbitro', '')
        juez = request.form.get('juez', '')
        jefe_tapiz = request.form.get('jefe_tapiz', '')
        
        estado = 'FINALIZADO' if accion == 'finalizar' else 'EN PROGRESO'
        
        if accion == 'finalizar' and not ganador_id:
            flash('Debe seleccionar un ganador antes de finalizar el combate.', 'danger')
            conn.close()
            return redirect(url_for('mesa_control', combate_id=combate_id))

        conn.execute('''
            UPDATE combates 
            SET puntos_rojo = ?, puntos_azul = ?, ganador_id = ?, tipo_victoria = ?, 
                estado = ?, arbitro = ?, juez = ?, jefe_tapiz = ?
            WHERE id = ?
        ''', (puntos_rojo, puntos_azul, ganador_id if ganador_id else None, forma_victoria, 
              estado, arbitro, juez, jefe_tapiz, combate_id))
        
        if accion == 'finalizar':
            avanzar_clasificado_bracket(conn, combate_id, ganador_id)
            conn.commit()
            
            combate_recabezado = conn.execute('SELECT modalidad, categoria_peso FROM combates WHERE id = ?', (combate_id,)).fetchone()
            cat_param = f"{combate_recabezado['modalidad']} - {combate_recabezado['categoria_peso']}"
            conn.close()
            
            flash('Combate finalizado y procesado.', 'success')
            return redirect(url_for('admin_sorteo', categoria=cat_param))
        else:
            conn.commit()
            flash('Marcador actualizado.', 'info')

    combate = conn.execute('''
        SELECT c.*, 
               r.nombre_completo AS rojo_nombre, r.dorsal AS rojo_dorsal, r.club AS rojo_club,
               a.nombre_completo AS azul_nombre, a.dorsal AS azul_dorsal, a.club AS azul_club
        FROM combates c
        LEFT JOIN atletas r ON c.atleta_rojo_id = r.id
        LEFT JOIN atletas a ON c.atleta_azul_id = a.id
        WHERE c.id = ?
    ''', (combate_id,)).fetchone()
    
    conn.close()
    return render_template('administrador/mesa_control.html', combate=combate)

# ==========================================
# FUNCIONES AUXILIARES DE SORTEO Y BRACKETS
# ==========================================

def _generar_round_robin(lista_ids, modalidad, peso, tapiz, conn, ultimo_num):
    random.shuffle(lista_ids)
    n = len(lista_ids)
    num_combate = ultimo_num + 1
    mapa_atletas = {i + 1: lista_ids[i] for i in range(n)}

    tablas_uww = {
        2: [[(1, 2)]],
        3: [[(3, 2)], [(2, 1)], [(1, 3)]],
        4: [[(1, 2), (4, 3)], [(1, 4), (3, 2)], [(1, 3), (2, 4)]],
        5: [[(5, 2), (4, 3)], [(4, 1), (3, 2)], [(3, 5), (2, 1)], [(2, 4), (1, 5)], [(1, 3), (5, 4)]]
    }

    esquema_rondas = tablas_uww.get(n, [])

    for i, parejos in enumerate(esquema_rondas):
        num_ronda = i + 1
        for num_rojo, num_azul in parejos:
            rojo_id = mapa_atletas.get(num_rojo)
            azul_id = mapa_atletas.get(num_azul)

            if rojo_id and azul_id:
                conn.execute('''
                    INSERT INTO combates (tapiz, numero_combate, ronda, grupo, fase, modalidad, categoria_peso, atleta_rojo_id, atleta_azul_id)
                    VALUES (?, ?, ?, 'Round Robin', 'Grupos', ?, ?, ?, ?)
                ''', (tapiz, num_combate, num_ronda, modalidad, peso, rojo_id, azul_id))
                num_combate += 1

def _generar_sistema_nordico(lista_ids, modalidad, peso, tapiz, conn, ultimo_num):
    random.shuffle(lista_ids)
    mitad = len(lista_ids) // 2
    grupo_a, grupo_b = lista_ids[:mitad], lista_ids[mitad:]
    num_combate = ultimo_num + 1
    
    for rojo, azul in itertools.combinations(grupo_a, 2):
        conn.execute('''
            INSERT INTO combates (tapiz, numero_combate, ronda, grupo, fase, modalidad, categoria_peso, atleta_rojo_id, atleta_azul_id)
            VALUES (?, ?, 1, 'Grupo A', 'Grupos', ?, ?, ?, ?)
        ''', (tapiz, num_combate, modalidad, peso, rojo, azul))
        num_combate += 1

    for rojo, azul in itertools.combinations(grupo_b, 2):
        conn.execute('''
            INSERT INTO combates (tapiz, numero_combate, ronda, grupo, fase, modalidad, categoria_peso, atleta_rojo_id, atleta_azul_id)
            VALUES (?, ?, 1, 'Grupo B', 'Grupos', ?, ?, ?, ?)
        ''', (tapiz, num_combate, modalidad, peso, rojo, azul))
        num_combate += 1

def _generar_eliminatoria_directa(lista_ids, modalidad, peso, tapiz, conn, ultimo_num):
    random.shuffle(lista_ids)
    num_combate = ultimo_num + 1
    n_atletas = len(lista_ids)
    
    combates_ronda1 = []
    for i in range(0, n_atletas, 2):
        rojo = lista_ids[i]
        azul = lista_ids[i+1] if (i+1) < n_atletas else None
        
        if azul is None:
            conn.execute('''
                INSERT INTO combates (tapiz, numero_combate, ronda, grupo, fase, modalidad, categoria_peso, atleta_rojo_id, atleta_azul_id, ganador_id, tipo_victoria, estado)
                VALUES (?, ?, 1, 'Eliminatoria', 'Cuadro Principal', ?, ?, ?, NULL, ?, 'Pase Directo (Bye)', 'FINALIZADO')
            ''', (tapiz, num_combate, modalidad, peso, rojo, rojo))
        else:
            conn.execute('''
                INSERT INTO combates (tapiz, numero_combate, ronda, grupo, fase, modalidad, categoria_peso, atleta_rojo_id, atleta_azul_id)
                VALUES (?, ?, 1, 'Eliminatoria', 'Cuadro Principal', ?, ?, ?, ?)
            ''', (tapiz, num_combate, modalidad, peso, rojo, azul))
        combates_ronda1.append(num_combate)
        num_combate += 1

    n_combates_siguiente = len(combates_ronda1) // 2
    ronda_actual = 2
    while n_combates_siguiente >= 1:
        for _ in range(n_combates_siguiente):
            conn.execute('''
                INSERT INTO combates (tapiz, numero_combate, ronda, grupo, fase, modalidad, categoria_peso, atleta_rojo_id, atleta_azul_id)
                VALUES (?, ?, ?, 'Eliminatoria', 'Cuadro Principal', ?, ?, NULL, NULL)
            ''', (tapiz, num_combate, ronda_actual, modalidad, peso))
            num_combate += 1
        n_combates_siguiente //= 2
        ronda_actual += 1

def avanzar_clasificado_bracket(conn, combate_id, ganador_id):
    combate_actual = conn.execute('SELECT * FROM combates WHERE id = ?', (combate_id,)).fetchone()
    if not combate_actual:
        return

    modalidad = combate_actual['modalidad']
    peso = combate_actual['categoria_peso']
    fase = combate_actual['fase']

    if fase == 'Grupos' or 'Grupo' in str(combate_actual['grupo']):
        pendientes = conn.execute('''
            SELECT COUNT(*) FROM combates 
            WHERE modalidad = ? AND categoria_peso = ? AND estado != 'FINALIZADO'
        ''', (modalidad, peso)).fetchone()[0]

        if pendientes == 0:
            semis_existentes = conn.execute('''
                SELECT COUNT(*) FROM combates 
                WHERE modalidad = ? AND categoria_peso = ? AND ronda = 2
            ''', (modalidad, peso)).fetchone()[0]

            if semis_existentes == 0:
                def obtener_clasificados(grupo_nombre):
                    combates_grupo = conn.execute('''
                        SELECT ganador_id FROM combates 
                        WHERE modalidad = ? AND categoria_peso = ? AND grupo = ? AND ganador_id IS NOT NULL
                    ''', (modalidad, peso, grupo_nombre)).fetchall()
                    
                    conteo = {}
                    for c in combates_grupo:
                        gid = c['ganador_id']
                        conteo[gid] = conteo.get(gid, 0) + 1
                    
                    ordenados = sorted(conteo.items(), key=lambda x: x[1], reverse=True)
                    return [x[0] for x in ordenados]

                clasificados_A = obtener_clasificados('Grupo A')
                clasificados_B = obtener_clasificados('Grupo B')

                if len(clasificados_A) >= 2 and len(clasificados_B) >= 2:
                    primer_A, segundo_A = clasificados_A[0], clasificados_A[1]
                    primer_B, segundo_B = clasificados_B[0], clasificados_B[1]

                    ultimo_num = conn.execute("SELECT MAX(numero_combate) FROM combates").fetchone()[0] or 0
                    tapiz = combate_actual['tapiz']

                    conn.execute('''
                        INSERT INTO combates (tapiz, numero_combate, ronda, grupo, fase, modalidad, categoria_peso, atleta_rojo_id, atleta_azul_id)
                        VALUES (?, ?, 2, 'Semifinal 1', 'Semifinales', ?, ?, ?, ?)
                    ''', (tapiz, ultimo_num + 1, modalidad, peso, primer_A, segundo_B))

                    conn.execute('''
                        INSERT INTO combates (tapiz, numero_combate, ronda, grupo, fase, modalidad, categoria_peso, atleta_rojo_id, atleta_azul_id)
                        VALUES (?, ?, 2, 'Semifinal 2', 'Semifinales', ?, ?, ?, ?)
                    ''', (tapiz, ultimo_num + 2, modalidad, peso, primer_B, segundo_A))

                    conn.execute('''
                        INSERT INTO combates (tapiz, numero_combate, ronda, grupo, fase, modalidad, categoria_peso, atleta_rojo_id, atleta_azul_id)
                        VALUES (?, ?, 3, 'Gran Final', 'Final', ?, ?, NULL, NULL)
                    ''', (tapiz, ultimo_num + 3, modalidad, peso))

    else:
        if not ganador_id:
            return
        ronda_actual = combate_actual['ronda']
        
        combates_ronda = conn.execute('''
            SELECT id FROM combates 
            WHERE modalidad = ? AND categoria_peso = ? AND ronda = ?
            ORDER BY numero_combate ASC
        ''', (modalidad, peso, ronda_actual)).fetchall()
        
        ids_ronda = [c['id'] for c in combates_ronda]
        if combate_id not in ids_ronda:
            return
            
        posicion_en_ronda = ids_ronda.index(combate_id)
        posicion_siguiente_combate = posicion_en_ronda // 2
        siguiente_ronda = ronda_actual + 1

        combates_siguiente_ronda = conn.execute('''
            SELECT * FROM combates 
            WHERE modalidad = ? AND categoria_peso = ? AND ronda = ?
            ORDER BY numero_combate ASC
        ''', (modalidad, peso, siguiente_ronda)).fetchall()

        if posicion_siguiente_combate < len(combates_siguiente_ronda):
            siguiente_combate = combates_siguiente_ronda[posicion_siguiente_combate]
            if posicion_en_ronda % 2 == 0:
                conn.execute('UPDATE combates SET atleta_rojo_id = ? WHERE id = ?', (ganador_id, siguiente_combate['id']))
            else:
                conn.execute('UPDATE combates SET atleta_azul_id = ? WHERE id = ?', (ganador_id, siguiente_combate['id']))

# ==========================================
# MANEJADOR DE ERRORES (404 NOT FOUND)
# ==========================================
@app.errorhandler(404)
def page_not_found(e):
    return redirect(url_for('login'))

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)