# Otomatisasi Notion

Proyek ini bertujuan untuk mengotomatisasi interaksi dengan Notion menggunakan skrip Python. Ini dapat digunakan untuk berbagai tugas seperti menambahkan entri baru, memperbarui halaman yang ada, atau mengekstrak data dari database Notion.

## Fitur

*   **Integrasi Notion API**: Berinteraksi dengan Notion menggunakan API resmi.
*   **Otomatisasi Tugas**: Otomatiskan tugas berulang di Notion.
*   **Konfigurasi Mudah**: Konfigurasi proyek dengan variabel lingkungan.

## Instalasi

Untuk menjalankan proyek ini secara lokal, ikuti langkah-langkah berikut:

1.  **Kloning repositori:**
    ```bash
    git clone https://github.com/your-username/notomatisasi.git
    cd notomatisasi
    ```

2.  **Buat dan aktifkan virtual environment:**
    ```bash
    python -m venv venv
    source venv/bin/activate  # On Windows, use `venv\Scripts\activate`
    ```

3.  **Instal dependensi:**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Konfigurasi variabel lingkungan:**
    Buat file `.env` di root proyek berdasarkan `.env.example` dan isi dengan kredensial Notion API Anda.

    Contoh `.env`:
    ```
    NOTION_API_KEY=secret_YOUR_NOTION_API_KEY
    NOTION_DATABASE_ID=your_database_id
    ```

## Penggunaan

### Menjalankan dengan Python

Setelah instalasi dan konfigurasi, Anda dapat menjalankan skrip utama:

```bash
python main.py
```

Pastikan Anda telah mengkonfigurasi skrip `main.py` sesuai dengan kebutuhan otomatisasi spesifik Anda.

### Menjalankan dengan Docker

Untuk menjalankan aplikasi menggunakan Docker, ikuti langkah-langkah berikut:

1.  **Bangun citra Docker:**
    ```bash
    docker build -t notomatisasi .
    ```

2.  **Jalankan kontainer Docker:**
    ```bash
    docker run --env-file .env notomatisasi
    ```
    Pastikan file `.env` Anda ada di direktori root proyek.

## Kontribusi

Kontribusi dipersilakan! Silakan ajukan *pull request* atau buka *issue* untuk saran dan perbaikan.

## Lisensi

Proyek ini dilisensikan di bawah Lisensi MIT. Lihat file `LICENSE` untuk detail lebih lanjut.
