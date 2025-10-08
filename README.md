Run the script with python to extract a calender-csv file like below.

```python3 -m pip install --index-url https://pypi.org/simple beautifulsoup4 requests lxml
python3 team_portrait_to_gcal_csv.py \
  --url "https://bvbb-badminton.liga.nu/cgi-bin/WebObjects/nuLigaBADDE.woa/wa/teamPortrait?teamtable=230541&championship=BBMM+25%2F26&group=38059" \
  --out "wedding_ii.csv" \
  --duration 120```
