# -*- coding: utf-8 -*-
"""
UniGuide AI — Çok Katlı Navigasyon
Her kat ayrı DXF. Kat geçişi merdiven/asansör üzerinden yapılır
(aynı isim iki katta = aynı nokta).
"""

import math
import re

import ezdxf
import networkx as nx
from ezdxf.tools.text import plain_text
from shapely.geometry import LineString
from shapely.ops import unary_union

# kat_adi -> {"walls":..., "rooms":..., "bounds":..., "graph":..., "poi":...}
_KATLAR = {}
_BASLANGIC_KAT = None          # START_POINT hangi kattaysa
GECIS_ANAHTARLARI = ("MERDIVEN", "ASANSÖR", "ASANSOR", "YÜRÜYEN", "YURUYEN", "ESCALATOR")


def _mesafe(p1, p2):
    return math.hypot(p1[0] - p2[0], p1[1] - p2[1])


def _temizle(ham):
    """AutoCAD biçim kodlarını temizler."""
    t = plain_text(ham)
    t = re.sub(r"\\[A-Za-z][^;]*;", "", t)
    t = t.replace("\\P", " ").replace("\n", " ")
    t = t.replace("{", "").replace("}", "")
    return " ".join(t.split())


def kat_bul(oda_adi):
    """Oda kodundan katı çıkarır: AZ005 -> 'zemin', A120 -> 'kat1', B203 -> 'kat2'."""
    ad = oda_adi.strip().upper().replace("-", "").replace(" ", "")
    if len(ad) < 2 or not ad[0].isalpha():
        return None
    if ad[1] == "Z":
        return "zemin"
    if ad[1].isdigit():
        return f"kat{ad[1]}"
    return None


def blok_bul(oda_adi):
    """Oda kodundan bloku çıkarır: A120 -> 'A'."""
    ad = oda_adi.strip().upper()
    return ad[0] if ad and ad[0].isalpha() else None


def kat_yukle(kat_adi, dxf_yolu):
    """Bir katı okur ve _KATLAR'a ekler."""
    global _BASLANGIC_KAT

    doc = ezdxf.readfile(dxf_yolu)
    msp = doc.modelspace()
    graf = nx.Graph()

    # duvarlar + sınırlar
    walls = []
    min_x = min_y = float("inf")
    max_x = max_y = float("-inf")
    for e in msp:
        if e.dxf.layer == "Walls" and e.dxftype() in ("LINE", "LWPOLYLINE"):
            if e.dxftype() == "LINE":
                pts = [(e.dxf.start.x, e.dxf.start.y), (e.dxf.end.x, e.dxf.end.y)]
            else:
                pts = [(p[0], p[1]) for p in e.get_points()]
                if e.is_closed:
                    pts.append(pts[0])
            walls.append(pts)
            for p in pts:
                min_x, min_y = min(min_x, p[0]), min(min_y, p[1])
                max_x, max_y = max(max_x, p[0]), max(max_y, p[1])

    # koridorlar
    raw = []
    for e in msp:
        if e.dxf.layer == "Paths" and e.dxftype() in ("LINE", "LWPOLYLINE"):
            if e.dxftype() == "LINE":
                p1 = (round(e.dxf.start.x, 2), round(e.dxf.start.y, 2))
                p2 = (round(e.dxf.end.x, 2), round(e.dxf.end.y, 2))
                if p1 != p2:
                    raw.append(LineString([p1, p2]))
            else:
                pts = [(round(p[0], 2), round(p[1], 2)) for p in e.get_points()]
                temiz = [pts[0]]
                for p in pts[1:]:
                    if p != temiz[-1]:
                        temiz.append(p)
                if len(temiz) > 1:
                    raw.append(LineString(temiz))

    if raw:
        birlesik = unary_union(raw)
        cizgiler = [birlesik] if birlesik.geom_type == "LineString" else list(birlesik.geoms)
        for cizgi in cizgiler:
            koord = list(cizgi.coords)
            for i in range(len(koord) - 1):
                p1 = (round(koord[i][0], 2), round(koord[i][1], 2))
                p2 = (round(koord[i + 1][0], 2), round(koord[i + 1][1], 2))
                graf.add_edge(p1, p2, weight=_mesafe(p1, p2))

    # odalar
    rooms = {}
    for e in msp:
        if e.dxf.layer == "Rooms" and e.dxftype() in ("TEXT", "MTEXT"):
            ham = e.dxf.text if e.dxftype() == "TEXT" else e.text
            ad = _temizle(ham)
            if not ad:
                continue
            temel, k = ad, 1
            while ad in rooms:
                ad = f"{temel} {k}"
                k += 1
            pos = (e.dxf.insert.x, e.dxf.insert.y)
            rooms[ad] = pos
            min_x, min_y = min(min_x, pos[0]), min(min_y, pos[1])
            max_x, max_y = max(max_x, pos[0]), max(max_y, pos[1])

    poi = {}
    if graf.number_of_nodes() > 0:
        for ad, pos in rooms.items():
            poi[ad] = min(graf.nodes, key=lambda n: _mesafe(pos, n))

    _KATLAR[kat_adi] = {
        "walls": walls, "rooms": rooms, "graph": graf, "poi": poi,
        "bounds": {"min_x": min_x, "min_y": min_y, "max_x": max_x, "max_y": max_y},
    }

    if "START_POINT" in rooms:
        _BASLANGIC_KAT = kat_adi

    return len(rooms), graf.number_of_nodes()


def tum_mekanlar():
    """Tüm katlardaki mekân isimleri (tekrarsız, sıralı)."""
    hepsi = set()
    for k in _KATLAR.values():
        hepsi.update(k["rooms"].keys())
    return sorted(hepsi)


def mekan_kati(ad):
    """Bir mekânın hangi katta olduğunu bulur (önce koda bakar, sonra dosyalara)."""
    kod_kat = kat_bul(ad)
    if kod_kat and kod_kat in _KATLAR and ad in _KATLAR[kod_kat]["rooms"]:
        return kod_kat
    for kat, veri in _KATLAR.items():
        if ad in veri["rooms"]:
            return kat
    return None


def _gecis_sec(blok, kaynak_kat, hedef_kat, tercih="MERDIVEN"):
    """İki katta da bulunan bir geçiş noktası (merdiven/asansör) seçer."""
    if kaynak_kat not in _KATLAR or hedef_kat not in _KATLAR:
        return None
    ortak = set(_KATLAR[kaynak_kat]["rooms"]) & set(_KATLAR[hedef_kat]["rooms"])
    gecisler = [a for a in ortak if any(k in a.upper() for k in GECIS_ANAHTARLARI)]
    if not gecisler:
        return None
    # aynı bloktakini tercih et
    ayni_blok = [g for g in gecisler if blok and g.upper().rstrip().endswith(blok.upper())]
    aday = ayni_blok or gecisler
    tercihli = [g for g in aday if tercih in g.upper()]
    return (tercihli or aday)[0]


def _yol(kat, bas_ad, hedef_ad):
    """Aynı kat içinde iki mekân arası düğüm listesi + mesafe."""
    veri = _KATLAR[kat]
    poi = veri["poi"]
    if bas_ad not in poi or hedef_ad not in poi:
        return None, 0
    try:
        dugumler = nx.shortest_path(veri["graph"], poi[bas_ad], poi[hedef_ad], weight="weight")
    except nx.NetworkXNoPath:
        return None, 0
    mesafe = sum(_mesafe(dugumler[i], dugumler[i + 1]) for i in range(len(dugumler) - 1))
    return dugumler, mesafe

def _yonlendirme_olustur(dugumler):
    if not dugumler or len(dugumler) < 2:
        return [{"icon": "arrive", "text_tr": "Hedefe vardınız", "text_en": "You have arrived", "text_ar": "لقد وصلت", "mesafe": 0.0}]

    adimlar = []
    son_aci = math.degrees(math.atan2(dugumler[1][1] - dugumler[0][1], dugumler[1][0] - dugumler[0][0]))
    birikmis = _mesafe(dugumler[0], dugumler[1])
    gecerli_hareket = "straight"
    
    for i in range(1, len(dugumler) - 1):
        p1 = dugumler[i]
        p2 = dugumler[i+1]
        m = _mesafe(p1, p2)
        yeni_aci = math.degrees(math.atan2(p2[1] - p1[1], p2[0] - p1[0]))
        fark = (yeni_aci - son_aci + 360) % 360
        if fark > 180:
            fark -= 360
            
        if abs(fark) < 20:
            birikmis += m
        else:
            if gecerli_hareket == "straight":
                adimlar.append({"icon": "straight", "text_tr": f"{int(birikmis)} m düz ilerle", "text_en": f"Go straight for {int(birikmis)} m", "text_ar": f"امشِ مستقيماً {int(birikmis)} م", "mesafe": round(birikmis, 1)})
            elif gecerli_hareket == "left":
                adimlar.append({"icon": "left", "text_tr": f"Sola dön ve {int(birikmis)} m ilerle", "text_en": f"Turn left and go {int(birikmis)} m", "text_ar": f"انعطف يساراً وامشِ {int(birikmis)} م", "mesafe": round(birikmis, 1)})
            else:
                adimlar.append({"icon": "right", "text_tr": f"Sağa dön ve {int(birikmis)} m ilerle", "text_en": f"Turn right and go {int(birikmis)} m", "text_ar": f"انعطف يميناً وامشِ {int(birikmis)} م", "mesafe": round(birikmis, 1)})
            
            if fark > 0:
                gecerli_hareket = "right"
            else:
                gecerli_hareket = "left"
            birikmis = m
            son_aci = yeni_aci

    if gecerli_hareket == "straight":
        adimlar.append({"icon": "straight", "text_tr": f"{int(birikmis)} m düz ilerle", "text_en": f"Go straight for {int(birikmis)} m", "text_ar": f"امشِ مستقيماً {int(birikmis)} م", "mesafe": round(birikmis, 1)})
    elif gecerli_hareket == "left":
        adimlar.append({"icon": "left", "text_tr": f"Sola dön ve {int(birikmis)} m ilerle", "text_en": f"Turn left and go {int(birikmis)} m", "text_ar": f"انعطف يساراً وامشِ {int(birikmis)} م", "mesafe": round(birikmis, 1)})
    else:
        adimlar.append({"icon": "right", "text_tr": f"Sağa dön ve {int(birikmis)} m ilerle", "text_en": f"Turn right and go {int(birikmis)} m", "text_ar": f"انعطف يميناً وامشِ {int(birikmis)} م", "mesafe": round(birikmis, 1)})

    adimlar.append({"icon": "arrive", "text_tr": "Hedefe vardınız", "text_en": "You have arrived", "text_ar": "لقد وصلت", "mesafe": 0.0})
    return adimlar


def _oda_simgesi(ad):
    u = ad.upper()
    if "YÜRÜYEN" in u or "YURUYEN" in u or "ESCALATOR" in u:
        return "🪜⚡"
    if "KÜTÜPHANE" in u or "KUTUPHANE" in u:
        return "📚"
    if "KAFE" in u or "CAFETERIA" in u or "RESTORAN" in u:
        return "☕"
    if "ÖĞRENCİ" in u or "OGRENCI" in u or "İŞLERİ" in u:
        return "🎓"
    if "MERDİVEN" in u or "MERDIVEN" in u:
        return "🪜"
    if "ASANSÖR" in u or "ASANSOR" in u:
        return "🛗"
    if "GİRİŞ" in u or "GIRIS" in u or "START" in u:
        return "🚪"
    return "🏫"


def _svg_ciz(kat, dugumler, bas_ad, hedef_ad, baslik, genislik=740):
    """Bir katın haritasını, üzerinde rota ile SVG olarak çizer."""
    veri = _KATLAR[kat]
    b = veri["bounds"]
    dx, dy = b["max_x"] - b["min_x"], b["max_y"] - b["min_y"]
    o = genislik / dx

    # 180 derece döndür: başlangıç aşağıda kalsın
    def sx(x):
        return (b["max_x"] - x) * o + 16

    def sy(y):
        return (y - b["min_y"]) * o + 16

    W, H = dx * o + 32, dy * o + 44

    bp = veri["rooms"][bas_ad]
    hp = veri["rooms"][hedef_ad]
    nokta = [(sx(bp[0]), sy(bp[1]))]
    nokta += [(sx(p[0]), sy(p[1])) for p in (dugumler or [])]
    nokta += [(sx(hp[0]), sy(hp[1]))]
    d = "M " + " L ".join(f"{x:.1f} {y:.1f}" for x, y in nokta)

    s = [f'<svg xmlns="http://www.w3.org/2000/svg" width="100%" height="100%" viewBox="0 0 {W:.0f} {H:.0f}" '
         f'style="border-radius:16px">']
    s.append(f'<rect width="{W:.0f}" height="{H:.0f}" fill="#0b0f17"/>')
    
    # Ambient grid / outdoor backdrop lines
    s.append(f'<defs><pattern id="grid" width="40" height="40" patternUnits="userSpaceOnUse">'
             f'<path d="M 40 0 L 0 0 0 40" fill="none" stroke="rgba(255,255,255,0.03)" stroke-width="1"/></pattern></defs>')
    s.append(f'<rect width="{W:.0f}" height="{H:.0f}" fill="url(#grid)"/>')
    s.append(f'<text x="16" y="{H-10:.0f}" fill="#64748b" font-size="12" font-weight="700">{baslik}</text>')

    # Clean 2D Architectural Vector Walls
    for pts in veri["walls"]:
        if len(pts) < 2:
            continue
        path_data = "M " + " L ".join(f"{sx(p[0]):.1f} {sy(p[1]):.1f}" for p in pts)
        s.append(f'<path d="{path_data}" fill="rgba(15, 23, 42, 0.75)" stroke="#38bdf8" stroke-width="1.8" stroke-linejoin="round" opacity="0.9"/>')

    # Render ALL room names & icons crisply inside room walls without skipping
    for rm_ad, rm_pos in veri["rooms"].items():
        if rm_ad == "START_POINT":
            continue
        display_name = re.sub(r"\s+\d+$", "", rm_ad)
        rx, ry = sx(rm_pos[0]), sy(rm_pos[1])
        icon = _oda_simgesi(rm_ad)
        
        is_landmark = any(k in rm_ad.upper() for k in ["KÜTÜPHANE", "KUTUPHANE", "KAFE", "ÖĞRENCİ", "MESCİT", "GİRİŞ"])
        font_sz = "5.5" if is_landmark else "4.6"
        fill_col = "#38bdf8" if is_landmark else "rgba(255, 255, 255, 0.85)"
        font_wt = "800" if is_landmark else "700"

        s.append(f'<g class="room-label-tag">'
                 f'<text x="{rx:.1f}" y="{ry-4.5:.1f}" text-anchor="middle" font-size="5.2">{icon}</text>'
                 f'<text x="{rx:.1f}" y="{ry+4.5:.1f}" text-anchor="middle" fill="{fill_col}" '
                 f'font-size="{font_sz}" font-weight="{font_wt}" font-family="system-ui, sans-serif" '
                 f'style="paint-order: stroke; stroke: #090d16; stroke-width: 1.2px; stroke-linejoin: round;">{display_name}</text>'
                 f'</g>')

    s.append(f'<path d="{d}" class="campy-route-path" fill="none" stroke="#10b981" stroke-width="4" '
             f'stroke-linecap="round" stroke-linejoin="round" opacity="0.85"/>')
             
    mesafe_toplam = 0.0
    for i in range(len(nokta) - 1):
        x1, y1 = nokta[i]
        x2, y2 = nokta[i+1]
        uzunluk = math.hypot(x2 - x1, y2 - y1)
        aci_deg = math.degrees(math.atan2(y2 - y1, x2 - x1))

        gidecek = 80 - (mesafe_toplam % 80)
        curr = gidecek
        while curr < uzunluk:
            r = curr / uzunluk
            ax = x1 + r * (x2 - x1)
            ay = y1 + r * (y2 - y1)
            s.append(f'<polygon points="-3,-3 3,0 -3,3" fill="#fff" transform="translate({ax:.1f},{ay:.1f}) rotate({aci_deg:.1f})"/>')
            curr += 80

        mesafe_toplam += uzunluk

    s.append(f'<circle cx="{nokta[0][0]:.1f}" cy="{nokta[0][1]:.1f}" r="7" '
             f'fill="#10b981" stroke="#fff" stroke-width="2"/>')
    s.append(f'<circle cx="{nokta[-1][0]:.1f}" cy="{nokta[-1][1]:.1f}" r="8" fill="#ef4444" '
             f'stroke="#fff" stroke-width="2">'
             f'<animate attributeName="r" values="8;13;8" dur="1.6s" repeatCount="indefinite"/>'
             f'</circle>')

    # Yürüyen nokta: SMIL animateMotion bazı mobil tarayıcılarda döngüyü
    # güvenilir şekilde tekrarlamıyor. Bunun yerine JS tarafında
    # requestAnimationFrame + getPointAtLength ile sürekli döngü çalıştırılır
    # (bkz. index.html -> startMover). Gerçek (dünya) mesafe, kat başına
    # ölçek farkı gözetmeksizin tutarlı bir görsel yürüme hızı için
    # data-mesafe olarak eklenir.
    gercek_noktalar = [bp] + list(dugumler or []) + [hp]
    gercek_mesafe = sum(_mesafe(gercek_noktalar[i], gercek_noktalar[i + 1])
                         for i in range(len(gercek_noktalar) - 1))
    s.append(f'<circle class="campy-mover" data-mesafe="{gercek_mesafe:.1f}" '
             f'cx="{nokta[0][0]:.1f}" cy="{nokta[0][1]:.1f}" r="7" '
             f'fill="#fff" stroke="#10b981" stroke-width="3"/>')
    s.append("</svg>")
    return "\n".join(s)


def rota(hedef_ad, baslangic_ad="START_POINT", tercih="MERDIVEN"):
    """Herhangi bir mekândan herhangi bir mekâna rota.
    Aynı kattaysa tek harita, farklı kattaysa merdiven/asansör üzerinden iki aşama."""
    hedef_kat = mekan_kati(hedef_ad)
    bas_kat = mekan_kati(baslangic_ad)
    if hedef_kat is None or bas_kat is None:
        return None
    if hedef_ad == baslangic_ad:
        return None

    # --- aynı kat ---
    if hedef_kat == bas_kat:
        dugumler, mesafe = _yol(bas_kat, baslangic_ad, hedef_ad)
        if dugumler is None:
            return None
        
        yol_noktalari = [_KATLAR[bas_kat]["rooms"][baslangic_ad]] + (dugumler or []) + [_KATLAR[hedef_kat]["rooms"][hedef_ad]]
        
        return {
            "tip": "tek_kat",
            "kat": hedef_kat,
            "baslangic": baslangic_ad,
            "asamalar": [{
                "kat": hedef_kat, "hedef": hedef_ad, "mesafe": round(mesafe, 1),
                "svg": _svg_ciz(hedef_kat, dugumler, baslangic_ad, hedef_ad,
                                _kat_etiketi(hedef_kat)),
                "yonlendirmeler": _yonlendirme_olustur(yol_noktalari),
            }],
            "mesafe": round(mesafe, 1),
            "dakika": max(1, round(mesafe / 1.4 / 60)),
        }

    # --- farklı kat: geçiş noktası üzerinden ---
    gecis = _gecis_sec(blok_bul(hedef_ad), bas_kat, hedef_kat, tercih)
    if gecis is None:
        gecis = _gecis_sec(blok_bul(baslangic_ad), bas_kat, hedef_kat, tercih)
    if gecis is None:
        return None

    d1, m1 = _yol(bas_kat, baslangic_ad, gecis)
    d2, m2 = _yol(hedef_kat, gecis, hedef_ad)
    if d1 is None or d2 is None:
        return None
        
    yol_noktalari_1 = [_KATLAR[bas_kat]["rooms"][baslangic_ad]] + (d1 or []) + [_KATLAR[bas_kat]["rooms"][gecis]]
    yol_noktalari_2 = [_KATLAR[hedef_kat]["rooms"][gecis]] + (d2 or []) + [_KATLAR[hedef_kat]["rooms"][hedef_ad]]
    
    yon_1 = _yonlendirme_olustur(yol_noktalari_1)
    yon_2 = _yonlendirme_olustur(yol_noktalari_2)
    
    u_gecis = gecis.upper()
    if any(k in u_gecis for k in ["ASANSÖR", "ASANSOR"]):
        gecis_tipi, gecis_tr, gecis_en, gecis_ar = "elevator", "Asansör", "elevator", "المصعد"
    elif any(k in u_gecis for k in ["YÜRÜYEN", "YURUYEN", "ESCALATOR"]):
        gecis_tipi, gecis_tr, gecis_en, gecis_ar = "escalator", "Yürüyen Merdiven", "escalator", "الدرج الكهربائي"
    else:
        gecis_tipi, gecis_tr, gecis_en, gecis_ar = "stairs", "Merdiven", "stairs", "الدرج"
    
    if hedef_kat == "zemin":
        hedef_kat_str_tr, hedef_kat_str_en, hedef_kat_str_ar = "zemin kata", "ground floor", "الطابق الأرضي"
    elif "-" in hedef_kat:
        num = hedef_kat.replace("kat-", "")
        hedef_kat_str_tr = f"Bodrum -{num} katına"
        hedef_kat_str_en = f"Basement -{num} floor"
        hedef_kat_str_ar = f"طابق البدروم {num}-"
    else:
        num = hedef_kat.replace("kat", "")
        hedef_kat_str_tr = f"{num}. kata"
        hedef_kat_str_en = f"{num} floor"
        hedef_kat_str_ar = f"الطابق {num}"
    
    yon_1[-1] = {
        "icon": gecis_tipi,
        "text_tr": f"{gecis_tr} ile {hedef_kat_str_tr} git",
        "text_en": f"Go to {hedef_kat_str_en} using {gecis_en}",
        "text_ar": f"اذهب إلى {hedef_kat_str_ar} باستخدام {gecis_ar}",
        "mesafe": 0
    }

    toplam = m1 + m2
    return {
        "tip": "cok_kat",
        "gecis": gecis,
        "baslangic": baslangic_ad,
        "asamalar": [
            {"kat": bas_kat, "hedef": gecis, "mesafe": round(m1, 1),
             "svg": _svg_ciz(bas_kat, d1, baslangic_ad, gecis,
                             f"{_kat_etiketi(bas_kat)} \u2192 {gecis}"),
             "yonlendirmeler": yon_1},
            {"kat": hedef_kat, "hedef": hedef_ad, "mesafe": round(m2, 1),
             "svg": _svg_ciz(hedef_kat, d2, gecis, hedef_ad,
                             f"{_kat_etiketi(hedef_kat)} \u2192 {hedef_ad}"),
             "yonlendirmeler": yon_2},
        ],
        "mesafe": round(toplam, 1),
        "dakika": max(1, round(toplam / 1.4 / 60)),
    }


def _kat_etiketi(kat):
    if kat == "zemin":
        return "Zemin kat"
    if kat.startswith("kat-"):
        return f"Bodrum {kat.replace('kat', '')}"
    m = re.match(r"kat(\d+)", kat)
    return f"{m.group(1)}. kat" if m else kat
