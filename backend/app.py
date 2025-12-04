from flask import Flask, request, jsonify, send_from_directory, g
from openai import OpenAI
from flask_cors import CORS
from models import init_db
from dotenv import load_dotenv
import os, uuid, sqlite3, datetime

# Load environment variables
try:
    # Try multiple locations for .env file
    env_paths = ['.env', '../.env', '../../.env']
    env_loaded = False
    
    for env_path in env_paths:
        if os.path.exists(env_path):
            load_dotenv(dotenv_path=env_path)
            print(f"✅ Environment variables loaded from {env_path}")
            env_loaded = True
            break
    
    if not env_loaded:
        print("No .env file found, using system environment variables")
    
    print(f"DEBUG: Working directory: {os.getcwd()}")
    print(f"DEBUG: Checked paths: {env_paths}")
except Exception as e:
    print(f"Error loading environment variables: {e}")

app = Flask(__name__, static_folder='static', static_url_path='')
print("✅ Flask app created")

# Debug mode - print statements for troubleshooting

CORS(app, supports_credentials=True, origins=["https://flashvocab.benclason.com"])

try:
    client = OpenAI()  # Will automatically use OPENAI_API_KEY from environment
    print("✅ OpenAI client initialized successfully")
except Exception as e:
    print(f"Error initializing OpenAI client: {e}")
    client = None

try:
    init_db()
    print("✅ Database initialized successfully")
except Exception as e:
    print(f"Error initializing database: {e}")

DB_DIR = '/var/www/flash_vocab/backend/databases'
os.makedirs(DB_DIR, exist_ok=True)

def get_device_id():
    device_id = request.cookies.get('device_id')
    if not device_id:
        device_id = str(uuid.uuid4())

    db_path = os.path.join(DB_DIR, f"{device_id}.db")

    if not os.path.exists(db_path):
        conn = sqlite3.connect(db_path)
        # Initialize schema for new device database
        c = conn.cursor()
        
        # Create lists table
        c.execute('''
        CREATE TABLE IF NOT EXISTS lists (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            last_used TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')

        # Create cards table
        c.execute('''
            CREATE TABLE IF NOT EXISTS cards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                list_id INTEGER NOT NULL,
                chunk_id INTEGER default 0,
                term TEXT DEFAULT '',
                translation TEXT DEFAULT '',
                secondary_translation TEXT DEFAULT '',
                correct_attempts INTEGER DEFAULT 0,
                total_attempts INTEGER DEFAULT 0,
                starred BOOLEAN DEFAULT FALSE,
                FOREIGN KEY (list_id) REFERENCES lists(id) ON DELETE CASCADE
            )
        ''')
        
        conn.commit()
        conn.close()

    g.db = sqlite3.connect(db_path)
    return g.db, device_id

def get_db_connection(device_id):
    # make sure the databases folder exists
    os.makedirs(DB_DIR, exist_ok=True)

    # full path for this device's database file
    db_path = os.path.join(DB_DIR, f"{device_id}.db")

    # check if database needs initialization
    needs_init = not os.path.exists(db_path)

    # connect to the database
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    
    # Initialize schema if this is a new database
    if needs_init:
        c = conn.cursor()
        
        # Create lists table
        c.execute('''
        CREATE TABLE IF NOT EXISTS lists (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            last_used TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')

        # Create cards table
        c.execute('''
            CREATE TABLE IF NOT EXISTS cards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                list_id INTEGER NOT NULL,
                chunk_id INTEGER default 0,
                term TEXT DEFAULT '',
                translation TEXT DEFAULT '',
                secondary_translation TEXT DEFAULT '',
                correct_attempts INTEGER DEFAULT 0,
                total_attempts INTEGER DEFAULT 0,
                starred BOOLEAN DEFAULT FALSE,
                FOREIGN KEY (list_id) REFERENCES lists(id) ON DELETE CASCADE
            )
        ''')
        
        conn.commit()
    
    return conn


# # Add CORS headers to all responses
# @app.after_request
# def after_request(response):
#     response.headers.add('Access-Control-Allow-Origin', '*')
#     response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
#     response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
#     return response

# Test endpoint to verify CORS
# @app.route('/health', methods=['GET'])
# def health_check():
#     return jsonify({'status': 'healthy', 'message': 'Backend is running'}), 200

# @app.route('/test', methods=['GET'])
# def test_cors():
#     return jsonify({
#         'message': 'Backend is working!',
#         'cors_status': 'Allowing all origins',
#         'frontend_url': os.getenv('FRONTEND_URL', 'NOT SET'),
#         'flask_env': os.getenv('FLASK_ENV', 'NOT SET'),
#         'openai_key_set': 'SET' if os.getenv('OPENAI_API_KEY') else 'NOT SET',
#         'database_file': DB_FILE,
#         'database_exists': os.path.exists(DB_FILE),
#         'working_directory': os.getcwd(),
#         'env_file_exists': os.path.exists('.env'),
#         'port_info': 'Running on port 80 (no :5000 needed)'
#     })

# get all lists
@app.route('/lists', methods=['GET'])
def get_lists():
    device_id = request.cookies.get('device_id')
    if not device_id:
        device_id = str(__import__('uuid').uuid4())
    
    conn = get_db_connection(device_id)
    lists = conn.execute('SELECT * FROM lists').fetchall()
    conn.close()

    response = jsonify([dict(lst) for lst in lists])
    response.set_cookie('device_id', device_id, max_age=31536000)  # 1 year
    return response



@app.route('/lists/<int:id>', methods=['GET'])
def get_list(id):
    device_id = request.cookies.get('device_id')
    if not device_id:
        return jsonify({'error': 'Device ID not found'}), 400
        
    conn = get_db_connection(device_id)
    list_item = conn.execute('SELECT * FROM lists WHERE id = ?', (id,)).fetchone()
    conn.close()

    if list_item is None:
        return jsonify({'error': 'List not found'}), 404

    response = jsonify(dict(list_item))
    response.set_cookie('device_id', device_id, max_age=31536000)
    return response



@app.route('/lists', methods=['POST'])
def create_list():
    device_id = request.cookies.get('device_id')
    if not device_id:
        device_id = str(uuid.uuid4())
    
    data = request.get_json()
    name = data.get('name')
    last_used = (datetime.datetime.now()).timestamp()

    conn = get_db_connection(device_id)
    if not name:
        cursor = conn.cursor()
        num_lists = cursor.execute('SELECT COUNT(*) FROM lists').fetchone()[0]
        name = f'List {num_lists + 1}'

    conn.execute('INSERT INTO lists (name, last_used) VALUES (?, ?)', (name, last_used))
    list_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
    conn.commit()
    conn.close()

    response = jsonify({'id': list_id, 'name': name})
    response.set_cookie('device_id', device_id, max_age=31536000)  # 1 year
    return response, 201


@app.route('/lists/<int:id>', methods=['PUT'])
def update_list(id):
    try:
        device_id = request.cookies.get('device_id')
        if not device_id:
            return jsonify({'error': 'Device ID not found'}), 400
            
        data = request.get_json()
        print(f"DEBUG: PUT /lists/{id} received data: {data}")
        
        if not data:
            return jsonify({'error': 'No JSON data provided'}), 400
            
        name = data.get('name')
        last_used_input = data.get('last_used')
        
        # Handle different last_used formats
        if last_used_input:
            if isinstance(last_used_input, str):
                # Convert string timestamp to number
                try:
                    last_used = datetime.datetime.fromisoformat(last_used_input.replace(' ', 'T')).timestamp()
                except ValueError:
                    last_used = datetime.datetime.now().timestamp()
            else:
                last_used = last_used_input
        else:
            last_used = datetime.datetime.now().timestamp()

        if not name:
            return jsonify({'error': 'Name is required'}), 400

        conn = get_db_connection(device_id)
        conn.execute('UPDATE lists SET name = ?, last_used = ? WHERE id = ?', (name, last_used, id))
        conn.commit()
        conn.close()

        response = jsonify({'id': id, 'name': name, 'last_used': last_used})
        response.set_cookie('device_id', device_id, max_age=31536000)
        return response
    except Exception as e:
        error_msg = f"Error in update_list: {str(e)}"
        print(error_msg)
        return jsonify({'error': f'Internal server error: {str(e)}'}), 500


@app.route('/lists/<int:id>', methods=['DELETE'])
def delete_list(id):
    device_id = request.cookies.get('device_id')
    if not device_id:
        return jsonify({'error': 'Device ID not found'}), 400
        
    conn = get_db_connection(device_id)
    conn.execute('DELETE FROM lists WHERE id = ?', (id,))
    conn.commit()
    conn.close()

    response = jsonify({'message': 'List deleted successfully'})
    response.set_cookie('device_id', device_id, max_age=31536000)
    return response


@app.route('/lists/<int:list_id>/cards', methods=['GET'])
def get_cards_by_list(list_id):
    device_id = request.cookies.get('device_id')
    if not device_id:
        return jsonify({'error': 'Device ID not found'}), 400
        
    conn = get_db_connection(device_id)
    cards = conn.execute('SELECT * FROM cards WHERE list_id = ?', (list_id,)).fetchall()
    conn.close()

    response = jsonify([dict(card) for card in cards])
    response.set_cookie('device_id', device_id, max_age=31536000)
    return response


# do i have to specify the list_id?
@app.route('/cards/<int:id>', methods=['GET'])
def get_card(id):
    device_id = request.cookies.get('device_id')
    if not device_id:
        return jsonify({'error': 'Device ID not found'}), 400
        
    conn = get_db_connection(device_id)
    card = conn.execute('SELECT * FROM cards WHERE id = ?', (id,)).fetchone()
    conn.close()

    if card is None:
        return jsonify({'error': 'Card not found'}), 404

    response = jsonify(dict(card))
    response.set_cookie('device_id', device_id, max_age=31536000)
    return response


# without nesting this under lists i need to specify the list_id
@app.route('/cards', methods=['POST'])
def create_card():
    device_id = request.cookies.get('device_id')
    if not device_id:
        return jsonify({'error': 'Device ID not found'}), 400
        
    data = request.get_json()
    list_id = data.get('list_id')

    if not list_id:
        return jsonify({'error': 'List ID is required'}), 400

    conn = get_db_connection(device_id)
    cursor = conn.cursor()
    cursor.execute(
        'INSERT INTO cards (list_id) VALUES (?)',
        (list_id,)
    )
    conn.commit()
    new_id = cursor.lastrowid
    conn.close()

    response = jsonify({'id': new_id, 'list_id': list_id})
    response.set_cookie('device_id', device_id, max_age=31536000)
    return response, 201


# keeping this seperate from lists should be fine because each card has a unique id
@app.route('/cards/<int:id>', methods=['PUT'])
def update_card(id):
    try:
        device_id = request.cookies.get('device_id')
        if not device_id:
            return jsonify({'error': 'Device ID not found'}), 400
            
        data = request.get_json()
        print(f"DEBUG: PUT /cards/{id} received data: {data}")
        
        if not data:
            return jsonify({'error': 'No JSON data provided'}), 400
        
        # Handle field-value format (from edit page)
        field = data.get('field')
        value = data.get('value')
        
        # Handle direct field format (from accuracy updates)
        term = data.get('term')
        translation = data.get('translation')
        secondary_translation = data.get('secondary_translation', '')
        correct_attempts = data.get('correct_attempts')
        total_attempts = data.get('total_attempts')
        starred = data.get('starred')
        chunk_id = data.get('chunk_id')

        conn = get_db_connection(device_id)
        
        # Handle accuracy updates
        if correct_attempts is not None and total_attempts is not None:
            print(f"DEBUG: Updating accuracy for card {id}: {correct_attempts}/{total_attempts}")
            conn.execute(
                'UPDATE cards SET correct_attempts = ?, total_attempts = ? WHERE id = ?',
                (correct_attempts, total_attempts, id)
            )
        # Handle single field updates (field-value format)
        elif field and value is not None:
            allowed_fields = ['term', 'translation', 'secondary_translation', 'starred', 'chunk_id']
            if field not in allowed_fields:
                conn.close()
                return jsonify({'error': f'Invalid field: {field}'}), 400
            
            print(f"DEBUG: Updating field {field} = {value} for card {id}")
            query = f"UPDATE cards SET {field} = ? WHERE id = ?"
            conn.execute(query, (value, id))
        # Handle chunk_id updates
        elif chunk_id is not None:
            print(f"DEBUG: Updating chunk_id = {chunk_id} for card {id}")
            conn.execute(
                'UPDATE cards SET chunk_id = ? WHERE id = ?',
                (chunk_id, id)
            )
        # Handle direct field updates (for backward compatibility)
        elif term and translation:
            print(f"DEBUG: Updating term/translation for card {id}")
            conn.execute(
                'UPDATE cards SET term = ?, translation = ?, secondary_translation = ? WHERE id = ?',
                (term, translation, secondary_translation, id)
            )
        else:
            conn.close()
            print(f"DEBUG: Invalid update data for card {id}: {data}")
            return jsonify({'error': 'Invalid update data - missing required fields'}), 400
        
        conn.commit()
        conn.close()
        print(f"DEBUG: Successfully updated card {id}")

        response = jsonify({'message': 'Card updated successfully'})
        response.set_cookie('device_id', device_id, max_age=31536000)
        return response
        
    except Exception as e:
        error_msg = f"ERROR in update_card: {str(e)}"
        print(error_msg)
        return jsonify({'error': f'Internal server error: {str(e)}'}), 500


@app.route('/cards/<int:id>', methods=['DELETE'])
def delete_card(id):
    device_id = request.cookies.get('device_id')
    if not device_id:
        return jsonify({'error': 'Device ID not found'}), 400
        
    conn = get_db_connection(device_id)
    conn.execute('DELETE FROM cards WHERE id = ?', (id,))
    conn.commit()
    conn.close()

    response = jsonify({'message': 'Card deleted successfully'})
    response.set_cookie('device_id', device_id, max_age=31536000)
    return response


@app.route('/lists/<int:list_id>/reset-accuracy', methods=['PUT'])
def reset_list_accuracy(list_id):
    device_id = request.cookies.get('device_id')
    if not device_id:
        return jsonify({'error': 'Device ID not found'}), 400
        
    conn = get_db_connection(device_id)
    conn.execute(
        'UPDATE cards SET correct_attempts = 0, total_attempts = 0 WHERE list_id = ?', 
        (list_id,)
    )
    conn.commit()
    conn.close()

    response = jsonify({'message': 'All card accuracies reset successfully'})
    response.set_cookie('device_id', device_id, max_age=31536000)
    return response



# Group words using OpenAI (from AISorting.py)
@app.route('/group-words', methods=['POST'])
def group_words():
    try:
        data = request.get_json()
        words = data.get('words', [])
        if not isinstance(words, list) or not all(isinstance(w, str) for w in words):
            return jsonify({'error': 'Invalid input, expected a list of words'}), 400

        print(f"Received words for grouping: {words}")

        # Create a cleaner prompt without problematic Unicode characters
        prompt = f"""You are a JSON generator. Your task is to group all of the given words into sets of 4–6 items each. 
Important rules:
1. Every word must appear in exactly one group. 
2. No group may have fewer than 4 or more than 6 items. 
3. Do not add or remove words. 
4. Return valid JSON only, with no commentary, in this exact format:
{{
  "groups": [
    ["word1", "word2", "word3", "word4"],
    ["word5", "word6", "word7", "word8"]
  ]
}}

Words to group: {words}"""

        print("Sending request to OpenAI...")
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"}
        )

        print("OpenAI response received")
        print(f"Response content: {response.choices[0].message.content}")

        # Parse the JSON content manually since .parsed might not be available
        import json
        result = json.loads(response.choices[0].message.content)
        
        return jsonify(result)
        
    except Exception as e:
        print(f"Error in group_words: {str(e)}")
        return jsonify({'error': f'Internal server error: {str(e)}'}), 500
    


@app.route('/')
def serve_index():
    return send_from_directory(app.static_folder, 'index.html')

@app.route('/<path:path>')
def serve_static_files(path):
    if os.path.exists(os.path.join(app.static_folder, path)):
        return send_from_directory(app.static_folder, path)
    return send_from_directory(app.static_folder, 'index.html')

import logging
logging.basicConfig(level=logging.DEBUG)
app.logger.setLevel(logging.DEBUG)
app.config['PROPAGATE_EXCEPTIONS'] = True


if __name__ == '__main__':
    import os
    port = int(os.environ.get('PORT', 5000))
    # debug_mode = os.environ.get('FLASK_ENV') == 'development'
    # app.run(host='0.0.0.0', port=port, debug=debug_mode)
    app.run(host='0.0.0.0', port=port, debug=True)