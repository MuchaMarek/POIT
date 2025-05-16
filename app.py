from flask import Flask, render_template, session, request, jsonify
from flask_socketio import SocketIO, emit, disconnect
from threading import Lock
import configparser as ConfigParser
import time
import json
import serial
import MySQLdb

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'
socketio = SocketIO(app)
thread = None
thread_lock = Lock()

# Globálne premenne
ser = None
monitoring = False
params = {'interval': 1.0, 'mode': 'monitor'}
session_data = []

# DB konfigurácia
config = ConfigParser.ConfigParser()
config.read('config.cfg')
myhost = config.get('mysqlDB', 'host')
myuser = config.get('mysqlDB', 'user')
mypasswd = config.get('mysqlDB', 'passwd')
mydb = config.get('mysqlDB', 'db')


# ========== UNIVERZÁLNE PREPÍNANIE ==========
def toggle_monitoring():
    global monitoring, session_data

    if not monitoring:
        session_data = []
        monitoring = True
        socketio.emit('info', 'Monitorovanie zapnuté.', namespace='/test')
    else:
        monitoring = False
        socketio.emit('info', 'Monitorovanie vypnuté.', namespace='/test')

        if session_data:
            try:
                db = MySQLdb.connect(host=myhost, user=myuser, passwd=mypasswd, db=mydb)
                cursor = db.cursor()
                json_data = json.dumps(session_data)
                cursor.execute("INSERT INTO meranie (hodnoty) VALUES (%s)", (json_data,))
                db.commit()
                db.close()

                with open("static/files/test.txt", "a", encoding="utf-8") as f:
                    f.write(json_data + "\n")
            except Exception as db_err:
                print("Chyba DB:", db_err)
            session_data = []


# ========== BACKGROUND THREAD ==========
def background_thread():
    global ser, monitoring, session_data
    while True:
        socketio.sleep(params.get('interval', 1.0))
        if ser and ser.is_open:
            try:
                line = ser.readline().decode().strip()
                print("prijaté:", line)

                if line == "Movement":
                    toggle_monitoring()
                else:
                    if monitoring:
                        try:
                            value = float(line)
                            timestamp = time.strftime("%H:%M:%S")
                            entry = {"timestamp": timestamp, "value": value}
                            session_data.append(entry)
                            socketio.emit('sensor_data', {'data': value}, namespace='/test')
                        except ValueError:
                            print("Ignorovaný vstup:", line)
            except Exception as e:
                print("Chyba pri čítaní zo senzora:", e)

    def hello():
        print("hello")

    def neviem():
        print("nieco pre dalsi commit")

# ========== ROUTES ==========
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/graph')
def graph():
    return render_template('graph.html')

@app.route('/data')
def get_data():
    return jsonify(session_data)

@app.route('/filedata/<int:line>', methods=['GET'])
def filedata(line):
    try:
        with open("static/files/test.txt", "r", encoding="utf-8") as f:
            lines = f.readlines()
            if 0 <= line - 1 < len(lines):
                json_data = lines[line - 1].strip()
                return jsonify(json.loads(json_data))
            else:
                return jsonify({"error": "Line index out of range"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/dbdata/<int:id>', methods=['GET'])
def dbdata(id):
    try:
        db = MySQLdb.connect(host=myhost, user=myuser, passwd=mypasswd, db=mydb)
        cursor = db.cursor()
        cursor.execute("SELECT hodnoty FROM meranie WHERE id = %s", (id,))
        result = cursor.fetchone()
        db.close()

        if result:
            json_data = result[0]
            return jsonify(json.loads(json_data))
        else:
            return jsonify({"error": "Záznam neexistuje"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ========== SOCKET.IO EVENTS ==========
@socketio.on('connect', namespace='/test')
def connect():
    emit('info', 'Klient pripojený.')

@socketio.on('open_event', namespace='/test')
def handle_open():
    global ser, thread
    try:
        ser = serial.Serial('/dev/ttyS2', 115200, timeout=1)
        if ser.is_open:
            with thread_lock:
                global thread
                if thread is None:
                    thread = socketio.start_background_task(background_thread)
            emit('open_response', {'message': 'Systém inicializovaný.'})
        else:
            emit('open_response', {'message': 'Nepodarilo sa otvoriť port.'})
    except Exception as e:
        emit('open_response', {'message': f'Chyba: {e}'})

@socketio.on('params_event', namespace='/test')
def handle_params(data):
    params['interval'] = float(data.get('interval', 1.0))
    params['mode'] = data.get('mode', 'monitor')
    emit('params_response', {'message': 'Parametre nastavené'})

@socketio.on('start_event', namespace='/test')
def start_monitoring():
    toggle_monitoring()

@socketio.on('stop_event', namespace='/test')
def stop_monitoring():
    toggle_monitoring()

@socketio.on('close_event', namespace='/test')
def close_app():
    global monitoring, ser
    if monitoring:
        toggle_monitoring()
    if ser and ser.is_open:
        ser.close()
    emit('info', 'Systém ukončený a port zatvorený.')
    disconnect()

@socketio.on('disconnect', namespace='/test')
def disconnect_client():
    print('Klient odpojený:', request.sid)


# ========== MAIN ==========
if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=80, debug=True)