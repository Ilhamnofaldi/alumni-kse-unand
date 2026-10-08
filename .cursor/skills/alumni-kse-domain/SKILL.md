---
name: alumni-kse-domain
description: Domain knowledge for Paguyuban Alumni Beasiswa KSE UNAND (Karya Salemba Empat Universitas Andalas). Use when working on alumni records, fakultas/jurusan Unand, angkatan, status kerja, atau copy UI bahasa Indonesia.
---

# Domain Alumni KSE UNAND

KSE = Karya Salemba Empat, beasiswa. Ini **paguyuban penerima beasiswa di Universitas Andalas**, bukan database alumni Unand secara umum.

Slogan yang sudah dipakai di UI: *Sharing · Network · Developing*.

## Istilah

| Di form CSV | Di kode / DB |
|---|---|
| Nama Lengkap Uda/uni | `full_name` |
| uda/uni? hehe | `gender` (L/P) |
| Angkatan | `cohort_year` (tahun masuk) |
| Tahun Lulus | `graduation_year` |
| Tahun terakhir nerima beasiswa KSE | `kse_last_year` |
| Tempat Kerja/kantor/Usaha | `workplace` (publik) |
| Alamat domisili | `domicile` (PII) |
| Kesan pesan | `testimonial` (publik di profil) |

"Uda/uni" adalah sapaan Minang; jangan dipakai sebagai label UI formal. UI memakai "alumni".

## Sumber data

File awal: ekspor Google Form `DATABASE ALUMNI KSE UNAND - Form Responses 1 (1).csv` (~331 baris, 15 kolom).

Dua kualitas data bercampur:

- ~103 baris form lengkap (ada timestamp)
- ~143 baris dari daftar kedua: nama + fakultas + jurusan + WA, tanpa angkatan/pekerjaan/kota

Jangan hapus baris yang belum lengkap. `perlu_dilengkapi` hanya untuk yang belum punya angkatan atau kota — bukan karena tempat kerja kosong. Beswan biasa tidak wajib punya jabatan; antrean `/admin?mutu=tanpa_jabatan` dipakai saat mengisi bagan, bukan sebagai cacat. `skeleton` khusus baris yang benar-benar cuma berisi nama.

## Fakultas Unand (kode stabil)

Sumber: `alumni_web/catalog.py` → `FACULTIES`. Jangan membuat kode baru jika alias sudah ada (FMIPA = MIPA = Matematika dan IPA).

## Status kerja

`bekerja` | `wirausaha` | `mahasiswa` | `belum_bekerja`

"Sudah Bekerja", "Freelance" → `bekerja`. "Enterpreneur"/Wiraswasta → `wirausaha`. "Koass" → `mahasiswa`.

## Jabatan paguyuban

Bukan kolom string di `alumni`. Riwayat ada di `alumni_kse_roles`: satu baris = satu periode kepengurusan, jabatan menempel ke periode itu. Satu orang boleh banyak baris (status berbeda tiap tahun, atau jabatan yang sama di periode lain). `scope` fakultas untuk PJ. Parser isian bebas: `alumni_web/offices.py`. Rentang `2022-2025` dipecah per tahun. Beswan biasa tidak wajib punya baris jabatan.

Anggota divisi punya kode per unit (`anggota_humas`, `anggota_pendidikan`, …). Kode lama `anggota_divisi` (belum spesifik) tetap sah dan tampil di ember sendiri pada bagan `/struktur` sampai diperbarui. Setiap divisi juga punya `sekbend_*` (sekretaris-bendahara). Bagan memakai template bawaan (inti, divisi + sekbend, PJ; seed awal slug `umum`) sebagai pola untuk periode yang *baru muncul*. Tahun yang sudah punya riwayat jabatan mendapat salinan sendiri, jadi menyunting template di `/admin/template` tidak mengubah riwayat. Pengurus boleh menambah template dan menentukan yang mana yang bawaan. Periode yang susunannya beda disesuaikan di `/admin/struktur`: sembunyikan divisi, jadikan sayap, atau tambah jabatan (contoh Comdev terpisah: ketua, sekbend, MnB, anggota). Kode jabatan tetap; yang berubah hanya susunan bagannya.

## Peta

Titik = kota/kabupaten dari teks domisili (`alumni_web/geocode.py`), **bukan rumah**. "Padang Panjang" jangan jadi "Padang".

## Nama situs

Produknya **direktori**, pengelolanya **paguyuban**. Masthead dan judul beranda memakai "Direktori Alumni … Karya Salemba Empat" dengan "Universitas Andalas" sebagai baris kedua. Paguyuban disebut sebagai pengelola di footer dan di halaman struktur, bukan sebagai nama situs. Jangan menggabung keduanya jadi satu judul panjang.

## Bahasa

UI, flash, dan README: Bahasa Indonesia. Nama variabel/kode: Inggris.

Tulis seperti menyapa sesama alumni: kalimat pendek, sapaan "Anda", dan alasan di balik aturan ikut disebut ("supaya satu titik tidak menunjuk ke satu orang"). Hindari istilah teknis dan kiasan arsip di teks yang dibaca pengguna: *ambang*, *agregat*, *kursi*, *jilid*, *lembar muka*, *saring*. Jangan pula memakai kalimat bantahan seperti "bukan direktori alumni Unand secara umum" sebagai kalimat pembuka.
