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
from shapely.geometry import LineString, MultiLineString
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


POI_BLOCK_MAP = {
    "BAY MESCIT": "C",
    "BAYAN MESCIT": "C",
    "MESCIT": "C",
    "MOSQUE": "C",
    "KÜTÜPHANE": "A",
    "REVIR": "A",
    "KIRTASIYE": "B",
}

def blok_bul(oda_adi):
    """Oda veya geçiş adından blok harfini çıkarır (Örn: A120 -> 'A', CB201 -> 'C', MERDİVEN C -> 'C')."""
    if not oda_adi:
        return None
    ad = oda_adi.strip().upper()

    # Explicit POI block overrides
    for key, blk in POI_BLOCK_MAP.items():
        if key in ad:
            return blk

    if ad.startswith("AB") or ad.startswith("AZ"):
        return "A"
    if ad.startswith("BB") or ad.startswith("BZ"):
        return "B"
    if ad.startswith("CB") or ad.startswith("CZ"):
        return "C"
    if ad.startswith("DB") or ad.startswith("DZ"):
        return "D"
    if ad.startswith("JB") or ad.startswith("JZ"):
        return "C"

    if "MERDİVEN" in ad or "MERDIVEN" in ad or "ASANSÖR" in ad or "ASANSOR" in ad:
        for char in reversed(ad):
            if char.isalpha() and char.isupper():
                return char

    # Match standard room codes like A120, B205, C101, J105
    if len(ad) >= 2 and ad[0] in ["A", "B", "C", "D", "J"]:
        if ad[1].isdigit() or ad[1] in ["B", "Z"]:
            return "C" if ad[0] == "J" else ad[0]

    return None


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
        # Build Shapely MultiLineString for wall geometry to ensure POIs snap through open doors
        wall_lines = [LineString(pts) for pts in walls if len(pts) >= 2]
        walls_geom = MultiLineString(wall_lines) if wall_lines else None
        graph_nodes = list(graf.nodes)

        for ad, pos in rooms.items():
            sorted_nodes = sorted(graph_nodes, key=lambda n: _mesafe(pos, n))
            valid_node = None
            if walls_geom:
                for n in sorted_nodes[:30]:
                    ray = LineString([pos, n])
                    if not ray.intersects(walls_geom):
                        valid_node = n
                        break
            poi[ad] = valid_node or sorted_nodes[0]

    _KATLAR[kat_adi] = {
        "walls": walls, "rooms": rooms, "graph": graf, "poi": poi,
        "bounds": {"min_x": min_x, "min_y": min_y, "max_x": max_x, "max_y": max_y},
    }

    for rm in rooms:
        u_rm = rm.upper()
        if "START_POINT" in u_rm or "ANA GİRİŞ" in u_rm or "ANA GIRIS" in u_rm or "GİRİŞ" in u_rm or "GIRIS" in u_rm:
            _BASLANGIC_KAT = kat_adi
            break

    return len(rooms), graf.number_of_nodes()


def _otomatik_yukle_if_empty():
    if not _KATLAR:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        data_dir = os.path.join(base_dir, "data")
        if os.path.exists(data_dir):
            for fname in sorted(os.listdir(data_dir)):
                if fname.endswith(".dxf"):
                    kat_key = fname[:-4]
                    kat_yukle(kat_key, os.path.join(data_dir, fname))


def tum_mekanlar():
    """Tüm katlardaki mekân isimleri (tekrarsız, sıralı)."""
    _otomatik_yukle_if_empty()
    hepsi = set()
    for k in _KATLAR.values():
        hepsi.update(k["rooms"].keys())
    return sorted(hepsi)


def _norm_mekan_ad(s):
    if not s:
        return ""
    s = str(s).strip().upper()
    s = s.replace("İ", "I").replace("I", "I").replace("İ", "I")
    s = s.replace("Ş", "S").replace("Ğ", "G").replace("Ü", "U").replace("Ö", "O").replace("Ç", "C")
    s = re.sub(r"[-\s_]", "", s)
    return s


def _varsayilan_baslangic():
    """Varsayılan başlangıç noktasını bulur (ANA GİRİŞ, START_POINT vb.)."""
    _otomatik_yukle_if_empty()
    for kat, data in _KATLAR.items():
        for rm in data["rooms"]:
            u_rm = rm.upper()
            if "ANA GİRİŞ" in u_rm or "ANA GIRIS" in u_rm or "START_POINT" in u_rm:
                return rm
    for kat, data in _KATLAR.items():
        for rm in data["rooms"]:
            if "GİRİŞ" in rm.upper() or "GIRIS" in rm.upper():
                return rm
    return "ANA GİRİŞ"


def _gercek_mekan_ad(ad, pref_kat=None):
    """Mekân adını katlardaki tam DWG ismiyle eşleştirir (esnek Türkçe/İngilizce harf duyarlılığı)."""
    _otomatik_yukle_if_empty()
    if not ad:
        return _varsayilan_baslangic()
    if ad.upper() in ["START_POINT", "START", "DEFAULT"]:
        return _varsayilan_baslangic()
    if pref_kat and pref_kat in _KATLAR:
        if ad in _KATLAR[pref_kat]["rooms"]:
            return ad
        norm_t = _norm_mekan_ad(ad)
        for rm in _KATLAR[pref_kat]["rooms"]:
            if _norm_mekan_ad(rm) == norm_t:
                return rm
    for kat, veri in _KATLAR.items():
        if ad in veri["rooms"]:
            return ad
    norm_t = _norm_mekan_ad(ad)
    for kat, veri in _KATLAR.items():
        for rm in veri["rooms"]:
            if _norm_mekan_ad(rm) == norm_t:
                return rm
    for kat, veri in _KATLAR.items():
        for rm in veri["rooms"]:
            n_rm = _norm_mekan_ad(rm)
            if norm_t in n_rm or n_rm in norm_t:
                return rm
    return ad


def mekan_kati(ad, pref_kat=None):
    """Bir mekânın hangi katta olduğunu bulur (önce tercih edilen kata/koda bakar, sonra esnek isim arar)."""
    ad_gercek = _gercek_mekan_ad(ad, pref_kat=pref_kat)
    if pref_kat and pref_kat in _KATLAR and ad_gercek in _KATLAR[pref_kat]["rooms"]:
        return pref_kat
    kod_kat = kat_bul(ad_gercek)
    if kod_kat and kod_kat in _KATLAR and ad_gercek in _KATLAR[kod_kat]["rooms"]:
        return kod_kat
    for kat, veri in _KATLAR.items():
        if ad_gercek in veri["rooms"]:
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

    # Ensure path stays strictly on top of drawn corridor DXF lines
    if dugumler and len(dugumler) >= 2:
        nokta = [(sx(p[0]), sy(p[1])) for p in dugumler]
    elif dugumler and len(dugumler) == 1:
        nokta = [(sx(bp[0]), sy(bp[1])), (sx(dugumler[0][0]), sy(dugumler[0][1]))]
    else:
        nokta = [(sx(bp[0]), sy(bp[1])), (sx(hp[0]), sy(hp[1]))]

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


def _en_yakin_wc(baslangic_ad, wc_type):
    """Öğrencinin bulunduğu kata/konuma en yakın WC'yi bulur."""
    bas_kat = mekan_kati(baslangic_ad) or "zemin"
    u_type = (wc_type or "").upper()
    candidates = []

    if bas_kat in _KATLAR:
        for rm in _KATLAR[bas_kat]["rooms"]:
            u_rm = rm.upper()
            if "WC" in u_rm:
                if "ERKEK" in u_type and "ERKEK" in u_rm:
                    candidates.append((bas_kat, rm))
                elif "KADIN" in u_type and "KADIN" in u_rm:
                    candidates.append((bas_kat, rm))
                elif "ENGELL" in u_type and "ENGELL" in u_rm:
                    candidates.append((bas_kat, rm))
                elif not any(k in u_type for k in ["ERKEK", "KADIN", "ENGELL"]):
                    candidates.append((bas_kat, rm))

    if not candidates:
        for kat, data in _KATLAR.items():
            for rm in data["rooms"]:
                u_rm = rm.upper()
                if "WC" in u_rm:
                    if "ERKEK" in u_type and "ERKEK" in u_rm:
                        candidates.append((kat, rm))
                    elif "KADIN" in u_type and "KADIN" in u_rm:
                        candidates.append((kat, rm))
                    elif "ENGELL" in u_type and "ENGELL" in u_rm:
                        candidates.append((kat, rm))
                    elif not any(k in u_type for k in ["ERKEK", "KADIN", "ENGELL"]):
                        candidates.append((kat, rm))

    if not candidates:
        return None

    best_cand = None
    min_dist = float("inf")
    for kat, rm in candidates:
        if kat == bas_kat and baslangic_ad in _KATLAR[bas_kat]["rooms"]:
            d_list, m = _yol(kat, baslangic_ad, rm)
            if d_list is not None and m < min_dist:
                min_dist = m
                best_cand = (kat, rm)
        else:
            pos_b = _KATLAR[bas_kat]["rooms"].get(baslangic_ad, (0, 0)) if bas_kat in _KATLAR else (0, 0)
            pos_r = _KATLAR[kat]["rooms"].get(rm, (0, 0))
            m = _mesafe(pos_b, pos_r) + (abs(_kat_degeri(bas_kat) - _kat_degeri(kat)) * 20.0)
            if m < min_dist:
                min_dist = m
                best_cand = (kat, rm)

    return best_cand or candidates[0]


def rota(hedef_ad, baslangic_ad="START_POINT", tercih="MERDIVEN"):
    """Herhangi bir mekândan herhangi bir mekâna rota.
    Aynı kattaysa tek harita, farklı kattaysa merdiven/asansör üzerinden iki aşama."""
    _otomatik_yukle_if_empty()
    bas_kat = mekan_kati(baslangic_ad)
    baslangic_ad = _gercek_mekan_ad(baslangic_ad, pref_kat=bas_kat)
    if bas_kat is None:
        bas_kat = mekan_kati(baslangic_ad)

    # Generic WC request handling: find closest WC to student's current floor/location
    u_h = (hedef_ad or "").upper()
    wc_target_kat = None
    if "WC" in u_h or any(k in u_h for k in ["HAMAM", "TOALET", "RESTROOM", "BATHROOM", "TUALET"]):
        res = _en_yakin_wc(baslangic_ad, hedef_ad)
        if res:
            wc_target_kat, hedef_ad = res

    hedef_ad = _gercek_mekan_ad(hedef_ad, pref_kat=wc_target_kat or bas_kat)
    hedef_kat = wc_target_kat or mekan_kati(hedef_ad, pref_kat=bas_kat)
    if hedef_kat is None or bas_kat is None:
        return None
    if hedef_ad == baslangic_ad and hedef_kat == bas_kat:
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

    # --- farklı kat: akıllı çok aşamalı küresel rota ---
    if _kat_degeri(hedef_kat) == -3 and _kat_degeri(bas_kat) >= -1:
        tercih = "YÜRÜYEN"
    return _multi_floor_route(bas_kat, baslangic_ad, hedef_kat, hedef_ad, tercih)


def _kat_degeri(kat):
    if kat == "zemin":
        return 0
    if kat.startswith("kat-"):
        try: return -int(kat[4:])
        except: return 0
    if kat.startswith("kat"):
        try: return int(kat[3:])
        except: return 0
    return 0


def _multi_floor_route(bas_kat, baslangic_ad, hedef_kat, hedef_ad, tercih="MERDIVEN"):
    G = nx.Graph()
    for kat, data in _KATLAR.items():
        g = data["graph"]
        for u, v, d in g.edges(data=True):
            G.add_edge((kat, u), (kat, v), weight=d.get("weight", _mesafe(u, v)))
        for rm_ad, pos in data["rooms"].items():
            poi_pt = data["poi"].get(rm_ad)
            if poi_pt:
                G.add_edge((kat, rm_ad), (kat, poi_pt), weight=0.1)

        # Ara katlarda (ör: kat-1) henüz meller/yollar çizilmemişse geçiş noktalarını birbirine bağla
        rooms = list(data["rooms"].keys())
        if len(rooms) >= 2 and g.number_of_edges() < 2:
            for r1 in rooms:
                for r2 in rooms:
                    if r1 != r2:
                        p1, p2 = data["rooms"][r1], data["rooms"][r2]
                        G.add_edge((kat, r1), (kat, r2), weight=_mesafe(p1, p2) or 5.0)

    target_block = blok_bul(hedef_ad) or blok_bul(baslangic_ad)

    katlar_list = list(_KATLAR.keys())
    for i in range(len(katlar_list)):
        for j in range(i + 1, len(katlar_list)):
            k1, k2 = katlar_list[i], katlar_list[j]
            dist_floors = abs(_kat_degeri(k1) - _kat_degeri(k2)) or 1
            ortak = set(_KATLAR[k1]["rooms"]) & set(_KATLAR[k2]["rooms"])
            for gecis_ad in ortak:
                if any(k in gecis_ad.upper() for k in GECIS_ANAHTARLARI):
                    is_esc = any(k in gecis_ad.upper() for k in ["YÜRÜYEN", "YURUYEN", "ESCALATOR"])
                    base_w = 1.5 if is_esc else 2.5
                    
                    # Blok eşleşmesi kontrolü: eğer hedef A bloğundaysa A merdiven/asansörüne öncelik ver
                    stair_blk = blok_bul(gecis_ad)
                    block_penalty = 0.0
                    if target_block and not is_esc:
                        if stair_blk and stair_blk != target_block:
                            block_penalty = 500.0  # Hedef blok ile eşleşmeyen merdivenlere yüksek ceza

                    # Kullanıcı tercihi (Asansör / Merdiven)
                    pref_penalty = 0.0
                    u_gecis = gecis_ad.upper()
                    if tercih in ["ASANSÖR", "ASANSOR"] and ("MERDİVEN" in u_gecis or "MERDIVEN" in u_gecis):
                        pref_penalty = 25.0
                    elif tercih in ["MERDİVEN", "MERDIVEN"] and ("ASANSÖR" in u_gecis or "ASANSOR" in u_gecis):
                        pref_penalty = 25.0

                    weight = (base_w * dist_floors) + block_penalty + pref_penalty
                    G.add_edge((k1, gecis_ad), (k2, gecis_ad), weight=weight)

    # أي طالب في طابق أعلى من أو يساوي -1 يتجه إلى kat-3 يُمنع عنه السلالم العادية المتصلة بـ kat-3 ويُجبر على الدرج الكهربائي
    if (_kat_degeri(bas_kat) >= -1 and _kat_degeri(hedef_kat) == -3) or (_kat_degeri(hedef_kat) >= -1 and _kat_degeri(bas_kat) == -3):
        for u, v in list(G.edges()):
            if u[0] != v[0] and ("kat-3" in [u[0], v[0]]) and not any(k in str(u[1]).upper() or k in str(v[1]).upper() for k in ["YÜRÜYEN", "YURUYEN", "ESCALATOR"]):
                G.remove_edge(u, v)

    try:
        p = nx.shortest_path(G, (bas_kat, baslangic_ad), (hedef_kat, hedef_ad), weight="weight")
    except Exception:
        return None

    seg_list = []
    curr_kat = p[0][0]
    curr_pts = []
    for kat, node in p:
        if kat != curr_kat:
            seg_list.append((curr_kat, curr_pts))
            curr_kat = kat
            curr_pts = [node]
        else:
            curr_pts.append(node)
    if curr_pts:
        seg_list.append((curr_kat, curr_pts))

    asamalar = []
    toplam_mesafe = 0.0

    for i in range(len(seg_list)):
        kat, nodes = seg_list[i]
        coord_nodes = [n for n in nodes if isinstance(n, tuple) and len(n) == 2 and isinstance(n[0], (int, float))]
        
        s_name = baslangic_ad if i == 0 else seg_list[i-1][1][-1]
        t_name = hedef_ad if i == len(seg_list) - 1 else nodes[-1]

        m = sum(_mesafe(coord_nodes[j], coord_nodes[j+1]) for j in range(len(coord_nodes)-1)) if len(coord_nodes) > 1 else 0.0
        toplam_mesafe += m

        yol_nok = []
        if s_name in _KATLAR[kat]["rooms"]:
            yol_nok.append(_KATLAR[kat]["rooms"][s_name])
        yol_nok.extend(coord_nodes)
        if t_name in _KATLAR[kat]["rooms"]:
            yol_nok.append(_KATLAR[kat]["rooms"][t_name])

        yon = _yonlendirme_olustur(yol_nok)

        if i < len(seg_list) - 1:
            next_kat = seg_list[i+1][0]
            gecis_node = str(t_name)
            u_gecis = gecis_node.upper()
            if any(k in u_gecis for k in ["ASANSÖR", "ASANSOR"]):
                gecis_tipi, gecis_tr, gecis_en, gecis_ar = "elevator", "Asansör", "elevator", "المصعد"
            elif any(k in u_gecis for k in ["YÜRÜYEN", "YURUYEN", "ESCALATOR"]):
                gecis_tipi, gecis_tr, gecis_en, gecis_ar = "escalator", "Yürüyen Merdiven", "escalator", "الدرج الكهربائي"
            else:
                gecis_tipi, gecis_tr, gecis_en, gecis_ar = "stairs", "Merdiven", "stairs", "الدرج"

            if next_kat == "zemin":
                h_tr, h_en, h_ar = "zemin kata", "ground floor", "الطابق الأرضي"
            elif "-" in next_kat:
                num = next_kat.replace("kat-", "")
                h_tr, h_en, h_ar = f"Bodrum -{num} katına", f"Basement -{num} floor", f"طابق البدروم {num}-"
            else:
                num = next_kat.replace("kat", "")
                h_tr, h_en, h_ar = f"{num}. kata", f"{num} floor", f"الطابق {num}"

            yon[-1] = {
                "icon": gecis_tipi,
                "text_tr": f"{gecis_tr} ile {h_tr} git",
                "text_en": f"Go to {h_en} using {gecis_en}",
                "text_ar": f"اذهب إلى {h_ar} باستخدام {gecis_ar}",
                "mesafe": 0
            }

        s_room = str(s_name) if str(s_name) in _KATLAR[kat]["rooms"] else list(_KATLAR[kat]["rooms"].keys())[0]
        t_room = str(t_name) if str(t_name) in _KATLAR[kat]["rooms"] else list(_KATLAR[kat]["rooms"].keys())[0]

        asamalar.append({
            "kat": kat,
            "hedef": str(t_name),
            "mesafe": round(m, 1),
            "svg": _svg_ciz(kat, coord_nodes, s_room, t_room, _kat_etiketi(kat)),
            "yonlendirmeler": yon
        })

    return {
        "tip": "cok_kat",
        "gecis": str(seg_list[0][1][-1]),
        "baslangic": baslangic_ad,
        "asamalar": asamalar,
        "mesafe": round(toplam_mesafe, 1),
        "dakika": max(1, round(toplam_mesafe / 1.4 / 60)),
    }


def _kat_etiketi(kat):
    if kat == "zemin":
        return "Zemin kat"
    if kat.startswith("kat-"):
        return f"Bodrum {kat.replace('kat', '')}"
    m = re.match(r"kat(\d+)", kat)
    return f"{m.group(1)}. kat" if m else kat
