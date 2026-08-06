from __future__ import annotations

from scorecard.load import read_export


def test_reads_windows_1252(tmp_path):
    path = tmp_path / "po.csv"
    path.write_bytes("EBELN;NAME1\r\n4500012003;Müller Präzisionsteile GmbH\r\n".encode("cp1252"))

    header, rows = read_export(path)

    assert header == ["ebeln", "name1"]
    assert rows == [["4500012003", "Müller Präzisionsteile GmbH"]]


def test_reads_utf8_with_bom(tmp_path):
    path = tmp_path / "po.csv"
    path.write_bytes("EBELN;NAME1\r\n4500012003;Anadolu Döküm\r\n".encode("utf-8-sig"))

    header, rows = read_export(path)

    assert header == ["ebeln", "name1"]
    assert rows == [["4500012003", "Anadolu Döküm"]]


def test_skips_blank_lines(tmp_path):
    path = tmp_path / "gr.csv"
    path.write_text("MBLNR;MENGE\n5000031001;8.600,000\n;\n\n5000031002;4.200,000\n", encoding="ascii")

    _, rows = read_export(path)

    assert [row[0] for row in rows] == ["5000031001", "5000031002"]
