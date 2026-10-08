"""Geocode kasar berbasis kamus kota/kabupaten. Bukan alamat rumah persis."""

from __future__ import annotations

import re
from typing import Optional

# needle lebih panjang dicek lebih dulu.
PLACES: list[tuple[tuple[str, ...], str, float, float, str]] = [
    (("padang panjang",), "Padang Panjang", -0.466, 100.401, "Sumatera Barat"),
    (("padang pariaman", "kabupaten padang pariaman"), "Padang Pariaman", -0.618, 100.280, "Sumatera Barat"),
    (("paguyuban kse", "limau manih", "kuranji", "nanggalo", "koto tangah", "air pacah", "gurun laweh", "padang timur", "padang sarai"), "Padang", -0.947, 100.417, "Sumatera Barat"),
    (("kota padang",), "Padang", -0.947, 100.417, "Sumatera Barat"),
    (("jakarta selatan", "jakarta utara", "jakarta timur", "jakarta barat", "jakarta pusat", "dki jakarta", "tebet"), "Jakarta", -6.208, 106.846, "DKI Jakarta"),
    (("tangerang", "tanggerang", "ciledug", "pasar kemis", "serpong", "jayanti"), "Tangerang", -6.178, 106.630, "Banten"),
    (("kota serang", "serang banten", "serang - banten", "persada banten", "serang"), "Serang", -6.120, 106.150, "Banten"),
    (("cileungsi", "cibinong"), "Bogor", -6.395, 106.822, "Jawa Barat"),
    (("cikarang", "jababeka"), "Bekasi", -6.262, 107.152, "Jawa Barat"),
    (("mandailing natal", "panyabungan", "kotasiantar"), "Mandailing Natal", 0.863, 99.560, "Sumatera Utara"),
    (
        ("padang sidimpuan", "padangsidimpuan", "padang sidempuan", "padangsidempuan"),
        "Padangsidimpuan",
        1.379,
        99.272,
        "Sumatera Utara",
    ),
    (("gunung tua",), "Gunung Tua", 1.500, 99.833, "Sumatera Utara"),
    (("nias selatan", "teluk dalam"), "Nias Selatan", 0.565, 97.820, "Sumatera Utara"),
    (("indragiri hulu", "pematang reba", "rengat"), "Indragiri Hulu", -0.470, 102.168, "Riau"),
    (("bagan batu",), "Bagan Batu", 1.700, 100.450, "Riau"),
    (("bangkinang", "kampar"), "Bangkinang", 0.340, 101.024, "Riau"),
    (("pasir pengaraian",), "Pasir Pengaraian", 0.883, 100.300, "Riau"),
    (("bengkulu utara", "putri hijau"), "Bengkulu Utara", -3.540, 102.170, "Bengkulu"),
    (("konawe kepulauan",), "Konawe Kepulauan", -4.150, 123.100, "Sulawesi Tenggara"),
    (("kapuas hulu", "silat hilir"), "Kapuas Hulu", 0.833, 112.933, "Kalimantan Barat"),
    (("kalimantan tengah",), "Kalimantan Tengah", -1.681, 113.382, "Kalimantan Tengah"),
    (("kalimantan barat",), "Kalimantan Barat", -0.132, 111.097, "Kalimantan Barat"),
    (("tanah datar", "batusangkar", "lima kaum", "sungai tarab", "salimpaung", "kumango"), "Batusangkar", -0.453, 100.577, "Sumatera Barat"),
    (("lubuk basung", "kab agam", "kab.agam", "sungai pua", "tiku"), "Agam", -0.276, 100.009, "Sumatera Barat"),
    (("lubuk sikaping",), "Lubuk Sikaping", 0.123, 100.166, "Sumatera Barat"),
    (("pasaman barat", "kinali"), "Pasaman Barat", 0.196, 99.345, "Sumatera Barat"),
    (("muaro sijunjung", "sijunjung"), "Sijunjung", -0.709, 100.977, "Sumatera Barat"),
    (("solok selatan", "lubuk gadang"), "Solok Selatan", -1.375, 101.250, "Sumatera Barat"),
    (("sungai penuh", "kerinci"), "Sungai Penuh", -2.075, 101.392, "Sumatera Barat"),
    (("pesisir selatan",), "Pesisir Selatan", -1.350, 100.550, "Sumatera Barat"),
    (("batang gasan", "sungai limau", "pilubang"), "Padang Pariaman", -0.618, 100.280, "Sumatera Barat"),
    (("bandar lampung",), "Bandar Lampung", -5.429, 105.262, "Lampung"),
    (("kota makassar", "makassar"), "Makassar", -5.147, 119.432, "Sulawesi Selatan"),
    (("banjarmasin",), "Banjarmasin", -3.319, 114.591, "Kalimantan Selatan"),
    (("yogyakarta",), "Yogyakarta", -7.797, 110.371, "DI Yogyakarta"),
    (("wonosobo",), "Wonosobo", -7.360, 109.900, "Jawa Tengah"),
    (("purwakarta",), "Purwakarta", -6.557, 107.443, "Jawa Barat"),
    (("karawang",), "Karawang", -6.327, 107.305, "Jawa Barat"),
    (("kota bandung", "bandung"), "Bandung", -6.917, 107.619, "Jawa Barat"),
    (("kota batam", "batam"), "Batam", 1.045, 104.030, "Kepulauan Riau"),
    (("pekanbaru",), "Pekanbaru", 0.507, 101.448, "Riau"),
    (("kota jambi", "jambi"), "Jambi", -1.610, 103.613, "Jambi"),
    (("dumai",), "Dumai", 1.667, 101.450, "Riau"),
    (("ketapang",), "Ketapang", -1.850, 109.983, "Kalimantan Barat"),
    (("bukittinggi",), "Bukittinggi", -0.306, 100.369, "Sumatera Barat"),
    (("payakumbuh",), "Payakumbuh", -0.230, 100.633, "Sumatera Barat"),
    (("pariaman",), "Pariaman", -0.626, 100.120, "Sumatera Barat"),
    (("kota medan", "medan"), "Medan", 3.595, 98.672, "Sumatera Utara"),
    (("bekasi",), "Bekasi", -6.238, 106.975, "Jawa Barat"),
    (("depok",), "Depok", -6.402, 106.794, "Jawa Barat"),
    (("bogor", "tenjo"), "Bogor", -6.595, 106.799, "Jawa Barat"),
    (("surabaya",), "Surabaya", -7.258, 112.752, "Jawa Timur"),
    (("bengkulu",), "Bengkulu", -3.792, 102.261, "Bengkulu"),
    (("jakarta",), "Jakarta", -6.208, 106.846, "DKI Jakarta"),
    (("padang",), "Padang", -0.947, 100.417, "Sumatera Barat"),
    (("solok",), "Solok", -0.789, 100.654, "Sumatera Barat"),
    (("riau",), "Riau", 0.294, 101.707, "Riau"),
]


def _norm(text: str) -> str:
    text = text.lower().replace("tanggerang", "tangerang")
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def geocode_domicile(text: Optional[str]) -> Optional[dict]:
    if not text:
        return None
    raw = text.strip()
    if raw in {"-", ".", "–"}:
        return None
    n = _norm(raw)
    if not n:
        return None
    ranked = sorted(PLACES, key=lambda p: max(len(x) for x in p[0]), reverse=True)
    for needles, label, lat, lng, province in ranked:
        if any(_norm(needle) in n for needle in needles):
            return {
                "city": label,
                "province": province,
                "lat": lat,
                "lng": lng,
            }
    return None
