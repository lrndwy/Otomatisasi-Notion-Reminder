import requests
import json
from datetime import datetime, timedelta
import os
import time # Import the time module for sleep functionality
from dotenv import load_dotenv

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
            print("Available database properties:")
            for prop_name, prop_info in db_data['properties'].items():
                prop_type = prop_info.get('type')
                print(f"  - {prop_name}: {prop_type}")
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

    def format_task_message(self, task):
        """Format pesan tugas untuk Telegram"""
        try:
            # Debug: Print struktur properties untuk melihat apa yang tersedia
            print("Available properties:")
            for prop_name, prop_data in task['properties'].items():
                print(f"  - {prop_name}: {prop_data.get('type', 'unknown type')}")

            # Mencari property title (bisa bernama berbeda)
            task_title = "Untitled Task"
            for prop_name, prop_data in task['properties'].items():
                if prop_data.get('type') == 'title':
                    title_array = prop_data.get('title', [])
                    if title_array and len(title_array) > 0:
                        task_title = title_array[0].get('text', {}).get('content', 'Untitled Task')
                    break

            task_url = task['url']

            # Mencari property date (bisa bernama berbeda)
            due_date = "Tidak ada tanggal"
            for prop_name, prop_data in task['properties'].items():
                if prop_data.get('type') == 'date':
                    date_info = prop_data.get('date')
                    if date_info:
                        due_date = date_info.get('start', 'Tidak ada tanggal')
                    break

            # Format pesan
            message = f"🔔 *Pengingat Tugas*\n\n"
            message += f"📋 *Tugas:* {task_title}\n"
            message += f"📅 *Tenggat:* {due_date}\n"
            message += f"🔗 *Link:* [Buka di Notion]({task_url})\n"

            # Determine the reminder message based on the offset
            # Note: self.current_offset_days will be set in run_reminder
            if hasattr(self, 'current_offset_days'):
                if self.current_offset_days == 0:
                    message += f"\n⏰ Jangan lupa untuk menyelesaikan tugas ini hari ini!"
                elif self.current_offset_days < 0:
                    message += f"\n⏰ Pengingat: Tugas ini jatuh tempo dalam {abs(self.current_offset_days)} hari!"
                else:
                    message += f"\n⏰ Pengingat: Tugas ini sudah lewat {self.current_offset_days} hari!"
            else:
                message += f"\n⏰ Pengingat tugas!" # Fallback if offset not set

            return message
        except Exception as e:
            print(f"Error formatting task message: {e}")
            print(f"Task structure: {json.dumps(task, indent=2, default=str)}")
            return None

    def send_telegram_message(self, message):
        """Mengirim pesan ke Telegram"""
        url = f"https://api.telegram.org/bot{self.telegram_bot_token}/sendMessage"

        payload = {
            'chat_id': self.telegram_chat_id,
            'text': message,
            'parse_mode': 'Markdown',
            'disable_web_page_preview': False
        }

        try:
            response = requests.post(url, json=payload)
            response.raise_for_status()
            return True
        except requests.exceptions.RequestException as e:
            print(f"Error sending Telegram message: {e}")
            return False

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
                        task_title = "Untitled Task"
                        for prop_name, prop_data in task['properties'].items():
                            if prop_data.get('type') == 'title':
                                title_array = prop_data.get('title', [])
                                if title_array and len(title_array) > 0:
                                    task_title = title_array[0].get('text', {}).get('content', 'Untitled Task')
                                break
                        print(f"✅ Notifikasi berhasil dikirim untuk: {task_title}")
                    else:
                        print(f"❌ Gagal mengirim notifikasi untuk tugas")

def main():
    """Fungsi utama"""
    bot = NotionTelegramBot()

    # Get interval from environment variable, default to 30 seconds
    try:
        interval_seconds = int(os.getenv('CHECK_INTERVAL_SECONDS', 30))
    except ValueError:
        print("Invalid value for CHECK_INTERVAL_SECONDS. Using default of 30 seconds.")
        interval_seconds = 30

    print(f"Program akan melakukan pengecekan setiap {interval_seconds} detik.")

    while True:
        bot.run_reminder()
        print(f"Menunggu {interval_seconds} detik sebelum pengecekan berikutnya...")
        time.sleep(interval_seconds)

if __name__ == "__main__":
    main()
