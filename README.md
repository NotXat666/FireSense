<p align="center">
  <img src="assets/banner.png" alt="FireSense — Secure with Sense" width="820">
</p>

<h1 align="center">FireSense: Firewall Pintar yang Belajar Sendiri</h1>

> Firewall adaptif yang memakai **kecerdasan buatan (AI)** untuk mengenali dan memblokir
> serangan jaringan secara otomatis, tanpa perlu Anda menulis aturan (*rule*) satu per satu.

FireSense memantau lalu lintas jaringan pada firewall **OPNsense** setiap 30 detik. Sebuah
model AI (*Deep Q-Network*) lalu memutuskan tindakan yang tepat, yaitu membiarkan, memblokir,
memperketat, atau membuka blokir, dan langsung menerapkannya ke firewall.

Proyek ini adalah Tugas Akhir program **Rekayasa Keamanan Siber, Politeknik Siber dan Sandi Negara**.

---

## ❓ Apa yang saya dapat dari repo ini?

Ada **dua bagian** yang bisa Anda pakai sesuai kebutuhan:

| Bagian | Untuk siapa | Isi |
|--------|-------------|-----|
| 🖥️ **FireSense** (`FireSense/`) | **Pengguna umum** | Aplikasi desktop dengan tampilan grafis. Cukup klik-klik untuk menghubungkan ke OPNsense, menyalakan proteksi, dan memantau keputusan AI secara langsung. |
| ⌨️ **FireSenseCli** (`FireSenseCli/`) | Pengguna teknis / peneliti | Versi baris perintah (*command line*) untuk melatih ulang model, menjalankan *deployment*, dan eksperimen. |

Model AI yang sudah **terlatih** juga disertakan (`checkpoints/`), jadi Anda tidak perlu
melatih dari nol untuk mulai memakainya.

---

## 🧠 Apa yang dilakukan AI-nya?

Setiap 30 detik, AI memilih **satu** dari empat tindakan:

| Tindakan | Arti sederhana |
|----------|----------------|
| 🟢 **Maintain** | Lalu lintas aman, biarkan lewat |
| 🔴 **Block IP** | Sumber mencurigakan, blokir alamat IP-nya |
| 🟠 **Tighten** | Perketat aturan pada port berisiko (SSH/RDP/SMB) |
| 🔵 **Rollback** | Situasi sudah aman, buka kembali blokir |

---

## 🚀 Cara Pakai: Aplikasi FireSense (paling mudah)

**Prasyarat:** sebuah firewall **OPNsense** yang bisa Anda akses (bisa berupa mesin virtual),
dan komputer **Windows**.

### Langkah singkat

1. **Aktifkan API di OPNsense**
   Buka OPNsense → *System → Access → Users* → buat **API Key & Secret**. Simpan keduanya.

2. **Jalankan aplikasi FireSense**
   - **Pengguna umum (Windows):** unduh `FireSense_Setup.exe` dari halaman
     [**Releases**](../../releases) repo ini, jalankan installer-nya, lalu buka aplikasinya.
   - **Dari kode sumber:**
     ```bash
     cd FireSense
     pip install -r requirements.txt
     python main.py
     ```
     Untuk membangun installer `.exe` sendiri, jalankan `build.bat` (Windows).

3. **Isi Pengaturan (Setup)**
   Masukkan alamat OPNsense, API Key, dan API Secret Anda pada halaman *Setup*.

4. **Siapkan OPNsense otomatis**
   Klik tombol **🛠 Siapkan OPNsense Otomatis**. Aplikasi akan membuat sendiri
   *blocklist* dan aturan yang diperlukan (tidak perlu setting manual).

5. **Mulai proteksi**
   Klik **Mulai** di halaman *Deploy*. Pantau keputusan AI secara langsung di halaman
   *Dashboard* dan *Monitor*. Tombol **Panik** tersedia untuk menghentikan/menghapus blokir kapan saja.

---

## ⌨️ Cara Pakai: Versi Baris Perintah (teknis)

```bash
cd FireSenseCli

# 1. Siapkan lingkungan Python (butuh Python 3.12)
python -m venv myenv
source myenv/bin/activate          # Windows: myenv\Scripts\activate
pip install -r requirements.txt

# 2. Salin & isi konfigurasi (kredensial API TIDAK ikut di repo)
cp opnsense_config.example.py opnsense_config.py
#   lalu buka opnsense_config.py dan isi API_KEY, API_SECRET, dan alamat OPNsense

# 3. Jalankan deployment (siklus pantau, putuskan, terapkan)
python main_deploy.py

# (opsional) Latih ulang model dari dataset
python main_train.py
```

---

## 🗂️ Struktur Repo

```
FireSense/        Aplikasi desktop (GUI PyQt6) untuk pengguna umum
FireSenseCli/     Backend + CLI: pelatihan, inferensi, koneksi OPNsense
checkpoints/      Model DQN yang sudah terlatih (siap pakai) + scaler
log2.csv          Dataset pelatihan (Internet Firewall Data Set, Kaggle)
```

---

## 📚 Latar Belakang

FireSense mengadopsi dan **memvalidasi** pendekatan pada penelitian *FireRL* (Yang et al., 2025),
yang sebelumnya hanya diuji di simulasi, ke dalam *deployment* OPNsense nyata.
Dataset pelatihan: *Internet Firewall Data Set* (Kaggle).

## 👤 Penulis

Satwika Prabhawananda. Rekayasa Keamanan Siber, Politeknik Siber dan Sandi Negara.
