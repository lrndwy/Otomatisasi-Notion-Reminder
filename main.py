import requests
import json
from datetime import datetime, timedelta
import os
import time # Import the time module for sleep functionality
from dotenv import load_dotenv
import schedule
from flask import Flask, jsonify
import threading

# Load environment variables
load_dotenv()

class NotionTelegramBot:
    def __init__(self):
        # Konfigurasi API Keys
        self.notion_token = os.getenv('NOTION_TOKEN')
        self.telegram_bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
        self.telegram_chat_id = os.getenv('TELEGRAM_CHAT_ID')
        self.notion_database_id = os.getenv('NOTION_DATABASE_ID')
        # Allow multiple reminder offsets, comma-separated. Default to [0] for today.
        reminder_offsets_str = os.getenv('REMINDER_OFFSET_DAYS', '0')
        self.reminder_offset_days = [int(x.strip()) for x in reminder_offsets_str.split(',') if x.strip().lstrip('-').isdigit()]
        if not self.reminder_offset_days: # Fallback if parsing fails
            self.reminder_offset_days = [0]

        # File untuk menyimpan state terakhir database Notion
        self.state_file = 'notion_state.json'

        # Headers untuk Notion API
        self.notion_headers = {
            'Authorization': f'Bearer {self.notion_token}',
            'Content-Type': 'application/json',
            'Notion-Version': '2022-06-28'
        }

    def get_tasks_for_offset(self, offset_days):
        """Mengambil tugas yang tenggat waktunya sesuai offset hari dari Notion"""
        target_date = datetime.now() + timedelta(days=offset_days)
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

    def load_last_state(self):
        """Memuat state terakhir dari file."""
        if os.path.exists(self.state_file):
            with open(self.state_file, 'r') as f:
                return json.load(f)
        return {}

    def save_current_state(self, state):
        """Menyimpan state saat ini ke file."""
        with open(self.state_file, 'w') as f:
                json.dump(state, f, indent=2)

    def format_task_message(self, task, change_type="update"):
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
            if change_type == "add":
                message_header = f"✨ *Tugas Baru Ditambahkan!* oleh {created_by_name}"
            elif change_type == "delete":
                message_header = "🗑️ *Tugas Dihapus!*"
            elif change_type == "update":
                message_header = f"🔄 *Tugas Diperbarui!* oleh {last_edited_by_name}"
            else:
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

            # Determine the reminder message based on the offset (only for "update" type, which includes reminders)
            if change_type == "update" and hasattr(self, 'current_offset_days'):
                if self.current_offset_days == 0:
                    message += f"\n⏰ Jangan lupa untuk menyelesaikan tugas ini hari ini!"
                elif self.current_offset_days < 0:
                    message += f"\n⏰ Pengingat: Tugas ini jatuh tempo dalam {abs(self.current_offset_days)} hari!"
                else:
                    message += f"\n⏰ Pengingat: Tugas ini sudah lewat {self.current_offset_days} hari!"
            elif change_type == "update": # Fallback if offset not set for update type
                message += f"\n⏰ Pengingat tugas!"

            return message
        except Exception as e:
            print(f"Error formatting task message: {e}")
            print(f"Task structure: {json.dumps(task, indent=2, default=str)}")
            return None

    def check_for_notion_changes(self):
        """Memeriksa perubahan (add, edit, delete) di database Notion."""
        print("🔍 Memeriksa perubahan di database Notion...")
        current_tasks_list = self.get_all_tasks()
        current_tasks_map = {task['id']: task for task in current_tasks_list}

        last_state = self.load_last_state()
        last_tasks_map = {task_id: task_data for task_id, task_data in last_state.items()}

        # Deteksi tugas yang dihapus
        deleted_tasks = [task_id for task_id in last_tasks_map if task_id not in current_tasks_map]
        for task_id in deleted_tasks:
            deleted_task = last_tasks_map[task_id]
            message = self.format_task_message(deleted_task, change_type="delete")
            if message:
                self.send_telegram_message(message)
                print(f"🗑️ Notifikasi tugas dihapus: {self.get_task_title(deleted_task)}")

        # Deteksi tugas yang ditambahkan atau diperbarui
        for task_id, current_task in current_tasks_map.items():
            if task_id not in last_tasks_map:
                # Tugas baru ditambahkan
                message = self.format_task_message(current_task, change_type="add")
                if message:
                    self.send_telegram_message(message)
                    print(f"✨ Notifikasi tugas baru: {self.get_task_title(current_task)}")
            else:
                # Periksa apakah tugas diperbarui (sederhana: bandingkan last_edited_time)
                last_edited_time_current = current_task.get('last_edited_time')
                last_edited_time_previous = last_tasks_map[task_id].get('last_edited_time')

                if last_edited_time_current and last_edited_time_current != last_edited_time_previous:
                    message = self.format_task_message(current_task, change_type="update")
                    if message:
                        self.send_telegram_message(message)
                        print(f"🔄 Notifikasi tugas diperbarui: {self.get_task_title(current_task)}")

        # Simpan state saat ini
        self.save_current_state(current_tasks_map)
        print("✅ Pemeriksaan perubahan selesai. State Notion terbaru disimpan.")

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
                    self.send_telegram_message("✅ Kabar baik! Tidak ada tugas yang jatuh tempo hari ini.")
                elif offset < 0:
                    print(f"✅ Tidak ada tugas yang jatuh tempo dalam {abs(offset)} hari.")
                    self.send_telegram_message(f"✅ Tidak ada tugas yang jatuh tempo dalam {abs(offset)} hari.")
                else:
                    print(f"✅ Tidak ada tugas yang sudah lewat {offset} hari.")
                    self.send_telegram_message(f"✅ Tidak ada tugas yang sudah lewat {offset} hari.")
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

    # Jadwalkan pemeriksaan perubahan setiap interval tertentu (default 1 menit)
    schedule.every(change_check_interval).minutes.do(lambda: [bot.check_for_notion_changes(), update_bot_status("last_check")])
    print(f"Pemeriksaan perubahan dijadwalkan setiap {change_check_interval} menit")

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
        print("Tidak ada jadwal pengingat yang ditentukan. Menjalankan pengingat sekali.")
        bot.run_reminder() # Run reminder once if no schedule is set
        update_bot_status("last_reminder")

    # Jalankan pemeriksaan perubahan pertama kali
    bot.check_for_notion_changes()
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
