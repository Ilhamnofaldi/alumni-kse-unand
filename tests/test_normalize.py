from alumni_web.geocode import geocode_domicile
from alumni_web.import_csv import _header_map
from alumni_web.normalize import faculty_code, normalize_phone, parse_year, record_from_form, status_code


def test_phone_to_62():
    norm, _ = normalize_phone("81234567890")
    assert norm == "6281234567890"


def test_faculty_aliases():
    code, _ = faculty_code("FMIPA")
    assert code == "fmipa"
    code, _ = faculty_code("Fakultas Ekonomi")
    assert code == "feb"
    code, _ = faculty_code("Fakultas Teknologi Informasi")
    assert code == "fti"


def test_gender_uda_uni():
    from alumni_web.normalize import gender_code

    assert gender_code("Uda") == "L"
    assert gender_code("Uni") == "P"
    assert gender_code("Uda/uni") is None


def test_status_aliases():
    code, _ = status_code("Sudah Bekerja")
    assert code == "bekerja"
    code, _ = status_code("Enterpreneur")
    assert code == "wirausaha"
    code, _ = status_code("belum_bekerja")
    assert code == "belum_bekerja"


def test_year_range_and_belum_lulus():
    year, _ = parse_year("2011/2012")
    assert year == 2012
    year, raw = parse_year("Belum lulus")
    assert year is None
    assert raw


def test_header_map_ignores_name_for_gender():
    mapping = _header_map(
        [
            "Nama Lengkap Uda/uni siapa?",
            "uda/uni? hehe",
            "Status",
            "Email uda/uni apa?",
        ]
    )
    assert mapping["full_name"].startswith("Nama")
    assert "hehe" in mapping["gender"]
    assert mapping["status"] == "Status"


def test_geocode_padang_panjang_not_padang():
    rec = record_from_form({"full_name": "X", "domicile": "Padang Panjang"})
    assert rec["city"] == "Padang Panjang"


def test_geocode_padang_sidimpuan_not_padang():
    rec = record_from_form({"full_name": "X", "domicile": "Padang Sidimpuan"})
    assert rec["city"] == "Padangsidimpuan"


def test_geocode_serang():
    geo = geocode_domicile("Serang - Banten")
    assert geo and geo["city"] == "Serang"
    geo = geocode_domicile("Kota Serang")
    assert geo and geo["city"] == "Serang"
