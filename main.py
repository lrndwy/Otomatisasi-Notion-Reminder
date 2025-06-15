import requests
import json
from datetime import datetime, timedelta
import os
import time # Import the time module for sleep functionality
from dotenv import load_dotenv
import schedule
from flask import Flask, jsonify
import threading
import pytz

# Load environment variables
load_dotenv()

class NotionTelegramBot:
    def __init__(self):
        # Konfigurasi API Keys
        self.notion_token = os.getenv('NOTION_TOKEN')
        self.telegram_bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
        self.telegram_chat_id = os.getenv('TELEGRAM_CHAT_ID')
        self.notion_database_id = os.getenv('NOTION_DATABASE_ID')
        # Konfigurasi timezone, default ke UTC jika tidak diset
        self.timezone = pytz.timezone(os.getenv('TIMEZONE', 'UTC'))
        # Allow multiple reminder offsets, comma-separated. Default to [0] for today.
        reminder_offsets_str = os.getenv('REMINDER_OFFSET_DAYS', '0')
        self.reminder_offset_days = [int(x.strip()) for x in reminder_offsets_str.split(',') if x.strip().lstrip('-').isdigit()]
        if not self.reminder_offset_days: # Fallback if parsing fails
            self.reminder_offset_days = [0]

        # Configure weekly holidays (e.g., "Saturday,Sunday")
        weekly_holidays_str = os.getenv('WEEKLY_HOLIDAYS', '')
        self.weekly_holidays = [day.strip().lower() for day in weekly_holidays_str.split(',') if day.strip()]
        self.send_on_holidays = os.getenv('SEND_ON_HOLIDAYS', 'False').lower() == 'true'

        # Headers untuk Notion API
        self.notion_headers = {
            'Authorization': f'Bearer {self.notion_token}',
            'Content-Type': 'application/json',
            'Notion-Version': '2022-06-28'
        }

        # State management for change detection
        self.state_file = 'notion_state.json'
        self.last_known_state = self._load_state()
        # Determine if this is the initial run (no prior state loaded)
        self.is_initial_run = not bool(self.last_known_state)

    def _load_state(self):
        """Loads the last known state from a JSON file, validating its structure."""
        if os.path.exists(self.state_file):
            with open(self.state_file, 'r') as f:
                try:
                    state = json.load(f)
                    # Validate that all values in the state are dictionaries
                    if isinstance(state, dict) and all(isinstance(v, dict) for v in state.values()):
                        return state
                    else:
                        print(f"Warning: State file {self.state_file} contains invalid data format or is not a dictionary. Resetting state.")
                        return {}
                except json.JSONDecodeError:
                    print(f"Warning: Could not decode JSON from {self.state_file}. Starting with empty state.")
                    return {}
        return {}

    def _save_state(self):
        """Saves the current state to a JSON file."""
        with open(self.state_file, 'w') as f:
            json.dump(self.last_known_state, f, indent=2)

    def _get_simplified_task_state(self, task):
        """Extracts key properties from a Notion task for state comparison."""
        properties = task['properties']
        simplified_state = {
            'last_edited_time': task['last_edited_time'],
            'url': task['url'], # Include URL here
            'title': self.get_task_title(task), # Re-use existing helper
            'category': self._get_property_value_safe(properties, "Category", "select"),
            'assignee': self._get_property_value_safe(properties, "Assignee", "people"),
            'due_date': self._get_property_value_safe(properties, "Due Date", "date"),
            'status': self._get_property_value_safe(properties, "Status", "status"),
            'priority': self._get_property_value_safe(properties, "Priority", "select"),
            'description': self._get_property_value_safe(properties, "Description", "rich_text"),
            'progress': self._get_property_value_safe(properties, "Progress", "number"),
        }
        return simplified_state

    def _get_property_value_safe(self, properties, prop_name, prop_type):
        """Helper to safely get property value, similar to format_task_message but for internal use."""
        prop_data = properties.get(prop_name)
        if not prop_data:
            return "N/A"

        if prop_type == 'title':
            title_array = prop_data.get('title', [])
            return title_array[0].get('text', {}).get('content', 'N/A') if title_array else "N/A"
        elif prop_type == 'rich_text':
            rich_text_array = prop_data.get('rich_text', [])
            return rich_text_array[0].get('text', {}).get('content', 'N/A') if rich_text_array else "N/A"
        elif prop_type == 'date':
            date_info = prop_data.get('date')
            return date_info.get('start', 'N/A') if date_info else "N/A"
        elif prop_type == 'select':
            select_info = prop_data.get('select')
            return select_info.get('name', 'N/A') if select_info else "N/A"
        elif prop_type == 'status':
            status_info = prop_data.get('status')
            return status_info.get('name', 'N/A') if status_info else "N/A"
        elif prop_type == 'people':
            people_array = prop_data.get('people', [])
            return ", ".join([p.get('name', 'N/A') for p in people_array]) if people_array else "N/A"
        elif prop_type == 'number':
            return str(prop_data.get('number', 'N/A'))
        else:
            return "N/A"

    def get_tasks_for_offset(self, offset_days):
        """Mengambil tugas yang tenggat waktunya sesuai offset hari dari Notion"""
        target_date = datetime.now(self.timezone) + timedelta(days=offset_days)
        formatted_target_date = target_date.strftime('%Y-%m-%d')

        # Pertama, ambil struktur database untuk melihat properties yang tersedia
        db_url = f"https://api.notion.com/v1/databases/{self.notion_database_id}"

        try:
            db_response = requests.get(db_url, headers=self.notion_headers)
            db_response.raise_for_status()
            db_data = db_response.json()

            # Cari property bertipe date
            date_property = None
            # print("Available database properties:") # Debugging line, can be removed
            for prop_name, prop_info in db_data['properties'].items():
                prop_type = prop_info.get('type')
                # print(f"  - {prop_name}: {prop_type}") # Debugging line, can be removed
                if prop_type == 'date' and date_property is None:
                    date_property = prop_name

            if not date_property:
                print("❌ Tidak ditemukan property bertipe 'date' di database ini")
                return None

            print(f"✅ Menggunakan property '{date_property}' sebagai due date")

            # Query untuk mencari tugas dengan due date hari ini
            query = {
                "filter": {
                    "property": date_property,
                    "date": {
                        "equals": formatted_target_date
                    }
                }
            }

        except requests.exceptions.RequestException as e:
            print(f"Error fetching database structure: {e}")
            # Fallback ke query sederhana tanpa filter khusus
            query = {}

        url = f"https://api.notion.com/v1/databases/{self.notion_database_id}/query"

        try:
            response = requests.post(url, headers=self.notion_headers, json=query)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"Error fetching tasks from Notion: {e}")
            return None

    def get_all_tasks(self):
        """Mengambil semua tugas dari Notion database."""
        url = f"https://api.notion.com/v1/databases/{self.notion_database_id}/query"
        try:
            response = requests.post(url, headers=self.notion_headers)
            response.raise_for_status()
            return response.json().get('results', [])
        except requests.exceptions.RequestException as e:
            print(f"Error fetching all tasks from Notion: {e}")
            return []

    def check_for_changes(self):
        """Checks for changes in Notion tasks and sends notifications for new/updated tasks."""
        print("🔄 Memeriksa perubahan di Notion...")
        current_tasks_raw = self.get_all_tasks()
        if not current_tasks_raw:
            print("Tidak ada tugas yang ditemukan atau gagal mengambil tugas dari Notion.")
            return

        current_tasks_processed = {task['id']: self._get_simplified_task_state(task) for task in current_tasks_raw}

        new_state_to_save = {}

        # Identify new and updated tasks
        for task_id, current_task_state in current_tasks_processed.items():
            new_state_to_save[task_id] = current_task_state # Prepare for saving

            if task_id not in self.last_known_state:
                # New task
                print(f"🆕 Tugas baru terdeteksi: {current_task_state.get('title', 'Untitled Task')}")
                message = self._format_new_task_message(current_task_state)
                if message:
                    success = self.send_telegram_message(message)
                    if success:
                        print(f"✅ Notifikasi tugas baru berhasil dikirim untuk: {current_task_state.get('title', 'Untitled Task')}")
                    else:
                        print(f"❌ Gagal mengirim notifikasi tugas baru")
            else:
                # Existing task, check for updates
                old_task_state = self.last_known_state[task_id]
                if current_task_state != old_task_state:
                    print(f"✏️ Perubahan terdeteksi untuk tugas: {current_task_state.get('title', 'Untitled Task')}")
                    message = self._format_change_message(old_task_state, current_task_state)
                    if message:
                        success = self.send_telegram_message(message)
                        if success:
                            print(f"✅ Notifikasi perubahan berhasil dikirim untuk: {current_task_state.get('title', 'Untitled Task')}")
                        else:
                            print(f"❌ Gagal mengirim notifikasi perubahan")

        # Identify deleted tasks
        for task_id in self.last_known_state:
            if task_id not in current_tasks_processed:
                deleted_task_title = self.last_known_state[task_id].get('title', 'Untitled Task')
                print(f"🗑️ Tugas dihapus terdeteksi: {deleted_task_title}")
                message = f"🗑️ *Tugas Dihapus di Notion*\n\n" \
                          f"📋 *Tugas:* {deleted_task_title}\n" \
                          f"Tugas ini telah dihapus dari database Notion."
                success = self.send_telegram_message(message)
                if success:
                    print(f"✅ Notifikasi tugas dihapus berhasil dikirim untuk: {deleted_task_title}")
                else:
                    print(f"❌ Gagal mengirim notifikasi tugas dihapus")

        # Update the last known state and save it
        self.last_known_state = new_state_to_save
        self._save_state()
        print("✅ Pemeriksaan perubahan selesai.")

    def format_task_message(self, task):
        """Format pesan tugas untuk Telegram dengan detail yang lebih baik"""
        try:
            properties = task['properties']

            # Helper function to get property value safely
            def get_property_value(prop_name, prop_type):
                prop_data = properties.get(prop_name)
                if not prop_data:
                    return "N/A"

                if prop_type == 'title':
                    title_array = prop_data.get('title', [])
                    return title_array[0].get('text', {}).get('content', 'N/A') if title_array else "N/A"
                elif prop_type == 'rich_text':
                    rich_text_array = prop_data.get('rich_text', [])
                    return rich_text_array[0].get('text', {}).get('content', 'N/A') if rich_text_array else "N/A"
                elif prop_type == 'date':
                    date_info = prop_data.get('date')
                    return date_info.get('start', 'N/A') if date_info else "N/A"
                elif prop_type == 'select':
                    select_info = prop_data.get('select')
                    return select_info.get('name', 'N/A') if select_info else "N/A"
                elif prop_type == 'status':
                    status_info = prop_data.get('status')
                    return status_info.get('name', 'N/A') if status_info else "N/A"
                elif prop_type == 'people':
                    people_array = prop_data.get('people', [])
                    return ", ".join([p.get('name', 'N/A') for p in people_array]) if people_array else "N/A"
                elif prop_type == 'number':
                    return str(prop_data.get('number', 'N/A'))
                else:
                    return "N/A"

            # Helper function to get user name from 'created_by' or 'last_edited_by' objects
            def get_user_name(user_obj):
                if user_obj:
                    obj_type = user_obj.get('object')
                    if obj_type == 'person':
                        return user_obj.get('name', 'Unknown Person')
                    elif obj_type == 'bot':
                        # For bots, the name might be directly under the user_obj
                        # or in a nested 'bot' object. Try direct name first.
                        return user_obj.get('name', user_obj.get('bot', {}).get('owner', {}).get('user', {}).get('name', 'Unknown Bot'))
                return 'Unknown User'

            task_title = get_property_value("Task Name", "title")
            task_url = task['url']
            category = get_property_value("Category", "select")
            assignee = get_property_value("Assignee", "people")
            due_date = get_property_value("Due Date", "date")
            status = get_property_value("Status", "status")
            priority = get_property_value("Priority", "select")
            description = get_property_value("Description", "rich_text")
            progress = get_property_value("Progress", "number")

            created_by_name = get_user_name(task.get('created_by'))
            last_edited_by_name = get_user_name(task.get('last_edited_by'))

            # Format pesan
            message_header = "🔔 *Pengingat Tugas Notion*"

            message = f"{message_header}\n\n"
            message += f"📋 *Tugas:* {task_title}\n"
            message += f"🔗 *Link:* [Buka di Notion]({task_url})\n"
            message += f"--- Detail Tugas ---\n"
            message += f"🗓️ *Tenggat:* {due_date}\n"
            message += f"🏷️ *Kategori:* {category}\n"
            message += f"👤 *Ditugaskan Kepada:* {assignee}\n"
            message += f"📊 *Status:* {status}\n"
            message += f"❗ *Prioritas:* {priority}\n"
            message += f"📈 *Progress:* {progress}%\n"
            if description != "N/A":
                message += f"📝 *Deskripsi:* {description}\n"

            # Determine the reminder message based on the offset
            if hasattr(self, 'current_offset_days'):
                if self.current_offset_days == 0:
                    message += f"\n⏰ Jangan lupa untuk menyelesaikan tugas ini hari ini!"
                elif self.current_offset_days < 0:
                    message += f"\n⏰ Pengingat: Tugas ini jatuh tempo dalam {abs(self.current_offset_days)} hari!"
                else:
                    message += f"\n⏰ Pengingat: Tugas ini sudah lewat {self.current_offset_days} hari!"
            else: # Fallback if offset not set
                message += f"\n⏰ Pengingat tugas!"

            return message
        except Exception as e:
            print(f"Error formatting task message: {e}")
            print(f"Task structure: {json.dumps(task, indent=2, default=str)}")
            return None

    def _format_new_task_message(self, new_task_state):
        """Formats a message for a newly added task."""
        task_url = new_task_state.get('url', '#')
        message_header = "✨ *Tugas Baru Ditambahkan di Notion*"
        message = f"{message_header}\n\n"
        message += f"📋 *Tugas:* {new_task_state.get('title', 'N/A')}\n"
        message += f"🔗 *Link:* [Buka di Notion]({task_url})\n"
        message += f"--- Detail Tugas ---\n"
        message += f"🗓️ *Tenggat:* {new_task_state.get('due_date', 'N/A')}\n"
        message += f"🏷️ *Kategori:* {new_task_state.get('category', 'N/A')}\n"
        message += f"👤 *Ditugaskan Kepada:* {new_task_state.get('assignee', 'N/A')}\n"
        message += f"📊 *Status:* {new_task_state.get('status', 'N/A')}\n"
        message += f"❗ *Prioritas:* {new_task_state.get('priority', 'N/A')}\n"
        message += f"📈 *Progress:* {new_task_state.get('progress', 'N/A')}%\n"
        if new_task_state.get('description', 'N/A') != "N/A":
            message += f"📝 *Deskripsi:* {new_task_state.get('description', 'N/A')}\n"
        return message

    def _format_change_message(self, old_task_state, new_task_state):
        """Formats a message detailing changes between old and new task states."""
        changes = []
        for key, old_value in old_task_state.items():
            if key in ['last_edited_time', 'url']: # Skip these for change reporting
                continue
            new_value = new_task_state.get(key)
            if old_value != new_value:
                changes.append(f"- *{key.replace('_', ' ').title()}:* `{old_value}` ➡️ `{new_value}`")

        if not changes:
            return None # No significant changes to report (only last_edited_time or url changed, but content is same)

        task_url = new_task_state.get('url', '#')
        message_header = "✏️ *Perubahan Tugas di Notion*"
        message = f"{message_header}\n\n"
        message += f"📋 *Tugas:* {new_task_state.get('title', 'N/A')}\n"
        message += f"🔗 *Link:* [Buka di Notion]({task_url})\n"
        message += f"--- Detail Perubahan ---\n"
        message += "\n".join(changes)
        return message


    def get_task_title(self, task):
        """Helper untuk mendapatkan judul tugas dari objek tugas Notion."""
        for prop_name, prop_data in task['properties'].items():
            if prop_data.get('type') == 'title':
                title_array = prop_data.get('title', [])
                return title_array[0].get('text', {}).get('content', 'Untitled Task') if title_array else "Untitled Task"
        return "Untitled Task"

    def run_reminder(self):
        """Menjalankan pengingat tugas"""
        print("🚀 Memulai pengecekan tugas...")

        # Check if today is a weekly holiday, unless SEND_ON_HOLIDAYS is true
        today_name = datetime.now(self.timezone).strftime('%A').lower()
        if not self.send_on_holidays and today_name in self.weekly_holidays:
            print(f"🎉 Hari ini adalah hari libur mingguan ({today_name.capitalize()}). Tidak ada pengingat yang akan dikirim.")
            self.send_telegram_message(f"🎉 Hari ini adalah hari libur mingguan ({today_name.capitalize()}). Tidak ada pengingat yang akan dikirim.")
            return # Exit the function if it's a holiday and not configured to send on holidays

        # Iterate through each reminder offset
        for offset in self.reminder_offset_days:
            self.current_offset_days = offset # Store current offset for message formatting
            print(f"\n--- Memeriksa tugas dengan offset: {offset} hari ---")

            tasks_data = self.get_tasks_for_offset(offset)

            if not tasks_data:
                print("❌ Gagal mengambil data dari Notion")
                continue # Continue to the next offset if data fetching fails

            tasks = tasks_data.get('results', [])

            if not tasks:
                if offset == 0:
                    print("✅ Tidak ada tugas yang jatuh tempo hari ini")
                    print("✅ Tidak ada tugas yang jatuh tempo hari ini")
                elif offset < 0:
                    print(f"✅ Tidak ada tugas yang jatuh tempo dalam {abs(offset)} hari.")
                else:
                    print(f"✅ Tidak ada tugas yang sudah lewat {offset} hari.")
                continue # Continue to the next offset

            if offset == 0:
                print(f"📋 Ditemukan {len(tasks)} tugas yang jatuh tempo hari ini")
            elif offset < 0:
                print(f"📋 Ditemukan {len(tasks)} tugas yang jatuh tempo dalam {abs(offset)} hari")
            else:
                print(f"📋 Ditemukan {len(tasks)} tugas yang sudah lewat {offset} hari")

            # Kirim notifikasi untuk setiap tugas
            for task in tasks:
                message = self.format_task_message(task)
                if message:
                    success = self.send_telegram_message(message)
                    if success:
                        # Assuming 'Task Name' is the title property. Adjust if your Notion database uses a different name.
                        task_title = self.get_task_title(task)
                        print(f"✅ Notifikasi berhasil dikirim untuk: {task_title}")
                    else:
                        print(f"❌ Gagal mengirim notifikasi untuk tugas")

    def send_telegram_message(self, message):
        """Mengirim pesan ke Telegram"""
        telegram_url = f"https://api.telegram.org/bot{self.telegram_bot_token}/sendMessage"
        payload = {
            "chat_id": self.telegram_chat_id,
            "text": message,
            "parse_mode": "Markdown"
        }
        try:
            response = requests.post(telegram_url, json=payload)
            response.raise_for_status()
            return True
        except requests.exceptions.RequestException as e:
            print(f"Error mengirim pesan ke Telegram: {e}")
            return False

app = Flask(__name__)
bot_status = {"status": "initializing", "last_check": None, "last_reminder": None}

@app.route('/status')
def status():
    return jsonify(bot_status)

def run_flask_app():
    app.run(host='0.0.0.0', port=3000)

def main():
    """Fungsi utama"""
    bot = NotionTelegramBot()

    # Konfigurasi penjadwalan
    schedule_time = os.getenv("SCHEDULE_TIME", "") # Default to empty string
    schedule_interval_minutes = int(os.getenv("SCHEDULE_INTERVAL_MINUTES", "0")) # Default to 0 minutes
    change_check_interval = int(os.getenv("CHANGE_CHECK_INTERVAL", "1")) # Default to 1 minute


    # Jadwalkan pengingat tugas sesuai konfigurasi
    if schedule_time:
        schedule_times = [t.strip() for t in schedule_time.split(',') if t.strip()]
        for s_time in schedule_times:
            schedule.every().day.at(s_time).do(lambda: [bot.run_reminder(), update_bot_status("last_reminder")])
            print(f"Pengingat tugas dijadwalkan setiap hari pada pukul {s_time}")
    elif schedule_interval_minutes > 0:
        schedule.every(schedule_interval_minutes).minutes.do(lambda: [bot.run_reminder(), update_bot_status("last_reminder")])
        print(f"Pengingat tugas dijadwalkan setiap {schedule_interval_minutes} menit")
    else:
        print("Tidak ada jadwal pengingat yang ditentukan untuk pengingat tugas.")
        # bot.run_reminder() # Run reminder once if no schedule is set
        # update_bot_status("last_reminder")

    # Jadwalkan pengecekan perubahan secara dinamis
    if change_check_interval > 0:
        schedule.every(change_check_interval).minutes.do(lambda: [bot.check_for_changes(), update_bot_status("last_check")])
        print(f"Pengecekan perubahan Notion dijadwalkan setiap {change_check_interval} menit.")
    else:
        print("Tidak ada jadwal pengecekan perubahan yang ditentukan. Menjalankan pengecekan perubahan sekali.")
        bot.check_for_changes() # Run change check once if no schedule is set
        update_bot_status("last_check")


    # Start Flask app in a separate thread
    flask_thread = threading.Thread(target=run_flask_app)
    flask_thread.daemon = True # Allow main program to exit even if thread is running
    flask_thread.start()
    print("Server Flask berjalan di http://0.0.0.0:3000/status")

    bot_status["status"] = "running"

    try:
        while True:
            schedule.run_pending()
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nBot dihentikan.")
        bot_status["status"] = "stopped"

def update_bot_status(event_type):
    global bot_status
    current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    if event_type == "last_check":
        bot_status["last_check"] = current_time
    elif event_type == "last_reminder":
        bot_status["last_reminder"] = current_time

if __name__ == "__main__":
    main()
