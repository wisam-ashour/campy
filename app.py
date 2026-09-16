# -*- coding: utf-8 -*-
"""
Campy — Kampüs Rehberi
Biruni öğrencileri için iç mekân yön bulma.
Yapay zekâ çağrısı YOK — sadece harita. Hızlı ve limitsiz.
"""

import csv
import os
from datetime import datetime

from flask import Flask, render_template, request, jsonify

import navigasyon as nav

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
KAYIT_DIR = os.path.join(BASE_DIR, "kayit")
KAYIT_DOSYA = os.path.join(KAYIT_DIR, "kullanim.csv")

# --- katları yükle (bir kez, başlangıçta) ---
print(f"Kampüs planlari yukleniyor... ({DATA_DIR})")
if os.path.exists(DATA_DIR):
    for fname in sorted(os.listdir(DATA_DIR)):
        if fname.endswith(".dxf"):
            kat_key = fname[:-4]
            r = nav.kat_yukle(kat_key, os.path.join(DATA_DIR, fname))
            print(f"Kat '{kat_key}': {r[0]} mekan | {r[1]} dugum")
print(f"Toplam: {len(nav.tum_mekanlar())} mekan")

app = Flask(__name__)

KAYIT_GERIBILDIRIM = os.path.join(KAYIT_DIR, "geribildirim.csv")

os.makedirs(KAYIT_DIR, exist_ok=True)
if not os.path.exists(KAYIT_DOSYA):
    with open(KAYIT_DOSYA, "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow(["zaman", "baslangic", "hedef", "sonuc"])

if not os.path.exists(KAYIT_GERIBILDIRIM):
    with open(KAYIT_GERIBILDIRIM, "w", newline="", encoding="utf-8-sig") as f:
        csv.writer(f).writerow(["zaman", "dil", "kat", "mesaj"])


def _kaydet(baslangic, hedef, sonuc):
    """Kullanım istatistiği. Kişisel veri YOK — sadece hangi mekân ne kadar istendi."""
    try:
        with open(KAYIT_DOSYA, "a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow([
                datetime.now().strftime("%Y-%m-%d %H:%M"),
                baslangic, hedef, sonuc,
            ])
    except Exception:
        pass   # kayıt tutulamazsa servis durmasın


@app.route("/api/geribildirim", methods=["POST"])
def geribildirim():
    """Öğrencilerin harita/сайт hakkında bıraktığı geribildirimleri Excel/CSV dosyasına kaydeder."""
    veri = request.get_json() or {}
    mesaj = (veri.get("mesaj") or "").strip()
    dil = (veri.get("dil") or "tr").strip()
    kat = (veri.get("kat") or "").strip()

    if not mesaj:
        return jsonify({"durum": "hata", "mesaj": "mesaj_bos"})

    try:
        with open(KAYIT_GERIBILDIRIM, "a", newline="", encoding="utf-8-sig") as f:
            csv.writer(f).writerow([
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                dil,
                kat,
                mesaj,
            ])
    except Exception as e:
        print(f"Geri bildirim kayit hatasi: {e}")
        return jsonify({"durum": "hata", "mesaj": "kayit_basarisiz"})

    return jsonify({"durum": "ok", "mesaj": "kaydedildi"})


@app.route("/")
def index():
    return render_template("index.html")


@app.after_request
def add_header(response):
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response


@app.route("/api/mekanlar")
def mekanlar():
    """Arama kutusu için tüm mekân listesi."""
    return jsonify({"mekanlar": nav.tum_mekanlar()})


@app.route("/api/rota", methods=["POST"])
def rota():
    veri = request.get_json() or {}
    baslangic = (veri.get("baslangic") or "").strip()
    hedef = (veri.get("hedef") or "").strip()
    tercih = (veri.get("tercih") or "MERDIVEN").strip()

    if not hedef:
        return jsonify({"durum": "hata", "mesaj": "hedef_yok"})
    if not baslangic or baslangic.upper() in ["START_POINT", "START", "DEFAULT"]:
        baslangic = nav._varsayilan_baslangic()
    if baslangic == hedef:
        return jsonify({"durum": "hata", "mesaj": "ayni_yer"})

    sonuc = nav.rota(hedef, baslangic, tercih=tercih)
    if sonuc is None:
        _kaydet(baslangic, hedef, "bulunamadi")
        return jsonify({"durum": "hata", "mesaj": "rota_yok"})

    _kaydet(baslangic, hedef, "ok")
    return jsonify({
        "durum": "ok",
        "tip": sonuc["tip"],
        "mesafe": sonuc["mesafe"],
        "dakika": sonuc["dakika"],
        "gecis": sonuc.get("gecis"),
        "baslangic": baslangic,
        "hedef": hedef,
        "asamalar": [
            {"kat": a["kat"], "hedef": a["hedef"],
             "mesafe": a["mesafe"], "svg": a["svg"], "yonlendirmeler": a.get("yonlendirmeler", [])}
            for a in sonuc["asamalar"]
        ],
    })


if __name__ == "__main__":
    print("\nCampy calisiyor: http://127.0.0.1:5001\n")
    app.run(host="0.0.0.0", port=5001, debug=False)
