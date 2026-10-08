"""Master data fakultas, jurusan, status. Sumber kebenaran normalisasi CSV."""

FACULTIES = {
    "pertanian": "Pertanian",
    "teknik": "Teknik",
    "fateta": "Teknologi Pertanian",
    "fmipa": "FMIPA",
    "peternakan": "Peternakan",
    "feb": "FEB",
    "hukum": "Hukum",
    "fisip": "FISIP",
    "fkm": "Kesehatan Masyarakat",
    "farmasi": "Farmasi",
    "kedokteran": "Kedokteran",
    "fib": "Ilmu Budaya",
    "fti": "Teknologi Informasi",
    "keperawatan": "Keperawatan",
    "fkg": "Kedokteran Gigi",
    "lain": "Lainnya",
}

FACULTY_ALIASES = {
    "pertanian": "pertanian",
    "fakultas pertanian": "pertanian",
    "teknik": "teknik",
    "fakultas teknik": "teknik",
    "teknologi pertanian": "fateta",
    "fakultas teknologi pertanian": "fateta",
    "fateta": "fateta",
    "matematika dan ipa": "fmipa",
    "fmipa": "fmipa",
    "mipa": "fmipa",
    "fakultas mipa": "fmipa",
    "peternakan": "peternakan",
    "fakultas peternakan": "peternakan",
    "ekonomi": "feb",
    "feb": "feb",
    "fakultas ekonomi": "feb",
    "hukum": "hukum",
    "fakultas hukum": "hukum",
    "ilmu sosial dan politik": "fisip",
    "fisip": "fisip",
    "isip": "fisip",
    "fakultas isip": "fisip",
    "kesehatan masyarakat": "fkm",
    "fkm": "fkm",
    "farmasi": "farmasi",
    "fakultas farmasi": "farmasi",
    "kedokteran": "kedokteran",
    "fakultas kedokteran": "kedokteran",
    "fib": "fib",
    "sastra": "fib",
    "fakultas ilmu budaya": "fib",
    "teknologi informasi": "fti",
    "fti": "fti",
    "keperawatan": "keperawatan",
    "fakultas keperawatan": "keperawatan",
    "fkg": "fkg",
}

for _code, _label in FACULTIES.items():
    FACULTY_ALIASES.setdefault(_label.lower(), _code)
    FACULTY_ALIASES.setdefault(f"fakultas {_label.lower()}", _code)

MAJOR_ALIASES = {
    "thp": "Teknologi Hasil Pertanian",
    "teknologi hasil pertanian": "Teknologi Hasil Pertanian",
    "akutansi": "Akuntansi",
    "akuntansi": "Akuntansi",
    "t mesin": "Teknik Mesin",
    "mesin": "Teknik Mesin",
    "teknik mesin": "Teknik Mesin",
    "agrotek": "Agroteknologi",
    "agro": "Agroteknologi",
    "agroteknologi": "Agroteknologi",
    "agroekoteknologi": "Agroekoteknologi",
    "budidaya pertanian": "Agroekoteknologi",
    "agronomi": "Agroekoteknologi",
    "ilmu pertenakan": "Ilmu Peternakan",
    "ilmu peternakan": "Ilmu Peternakan",
    "peternakan": "Peternakan",
    "pembangunan dan bisnis peternakan": "Peternakan",
    "ilmu keperawatan+ners": "Ilmu Keperawatan",
    "ilmu keperawatan": "Ilmu Keperawatan",
    "pendidikan dokter gigi": "Pendidikan Dokter Gigi",
    "kedokteran gigi": "Pendidikan Dokter Gigi",
    "pendidikan dokter": "Pendidikan Dokter",
    "kesehatan masyarakat": "Ilmu Kesehatan Masyarakat",
    "ilmu kesehatan masyarakat": "Ilmu Kesehatan Masyarakat",
    "hukum": "Ilmu Hukum",
    "ilmu hukum": "Ilmu Hukum",
    "hukum internasioanal": "Hukum Internasional",
    "hukum internasional": "Hukum Internasional",
    "administrasi publik": "Ilmu Administrasi Negara",
    "ilmu administrasi negara": "Ilmu Administrasi Negara",
    "sistem komputer": "Sistem Komputer",
    "sastra jepang": "Sastra Jepang",
    "sastra inggris": "Sastra Inggris",
    "antropologi": "Antropologi Sosial",
    "antropologi sosial": "Antropologi Sosial",
    "farmasi": "Farmasi",
    "apoteker": "Farmasi",
}

STATUS_ALIASES = {
    "bekerja": "bekerja",
    "sudah bekerja": "bekerja",
    "freelance": "bekerja",
    "wirausaha": "wirausaha",
    "wiraswasta": "wirausaha",
    "enterpreneur": "wirausaha",
    "entrepreneur": "wirausaha",
    "mahasiswa": "mahasiswa",
    "koass (dokter muda)": "mahasiswa",
    "koass": "mahasiswa",
    "belum bekerja": "belum_bekerja",
    "belum_bekerja": "belum_bekerja",
    "belum kerja": "belum_bekerja",
    "mencari kerja": "belum_bekerja",
}

STATUS_LABELS = {
    "bekerja": "Bekerja",
    "wirausaha": "Wirausaha",
    "mahasiswa": "Mahasiswa",
    "belum_bekerja": "Belum bekerja",
}

GENDER_ALIASES = {
    "perempuan": "P",
    "wanita": "P",
    "p": "P",
    "uni": "P",
    "laki-laki": "L",
    "laki laki": "L",
    "pria": "L",
    "l": "L",
    "uda": "L",
}

PUBLIC_FIELDS = (
    "id",
    "full_name",
    "gender",
    "workplace",
    "status_code",
    "cohort_year",
    "graduation_year",
    "faculty_code",
    "faculty_raw",
    "major_normalized",
    "major_raw",
    "city",
    "province",
    "testimonial",
    "is_listed",
    "graduation_raw",
    "kse_last_year",
    "kse_last_raw",
)

# WhatsApp dan email: alumni atau pengurus yang sudah masuk.
CONTACT_FIELDS = (
    "phone",
    "phone_normalized",
    "email",
    "email_normalized",
)

# Alamat dan tanggal lahir: pemilik profil atau pengurus.
# lat/lng adalah centroid kota (bukan titik rumah), tetap ditutup di level
# individu; peta publik memakai agregat kota dengan ambang MAP_MIN_COUNT.
SENSITIVE_FIELDS = (
    "date_of_birth",
    "domicile",
    "lat",
    "lng",
)

# Gabungan untuk klasifikasi kolom. strip_pii() membagi CONTACT vs SENSITIVE.
PII_FIELDS = CONTACT_FIELDS + SENSITIVE_FIELDS

# Kolom kerja/audit: hanya pengurus. Tiga tuple ini harus mencakup seluruh
# kolom tabel alumni; dijaga oleh tests/test_privacy.py.
INTERNAL_FIELDS = (
    "name_normalized",
    "status_raw",
    "source",
    "submitted_at",
    "is_duplicate_suspect",
    "hide_requested",
    "self_updated_at",
    "data_quality_flags",
    "created_at",
    "updated_at",
)
