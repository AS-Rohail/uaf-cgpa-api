from flask import Flask, jsonify, request
from flask_cors import CORS
import requests
from bs4 import BeautifulSoup
import re
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__)
CORS(app)

GRADE_POINTS = {
    'A+': 4.00, 'A': 4.00, 'A-': 3.70,
    'B+': 3.30, 'B': 3.00, 'B-': 2.70,
    'C+': 2.30, 'C': 2.00, 'C-': 1.70,
    'D+': 1.30, 'D': 1.00, 'F': 0.00
}

def marks_to_grade(marks):
    try:
        m = float(marks)
        if m >= 90: return 'A+'
        elif m >= 85: return 'A'
        elif m >= 80: return 'A-'
        elif m >= 75: return 'B+'
        elif m >= 70: return 'B'
        elif m >= 65: return 'B-'
        elif m >= 60: return 'C+'
        elif m >= 55: return 'C'
        elif m >= 50: return 'C-'
        elif m >= 45: return 'D+'
        elif m >= 40: return 'D'
        else: return 'F'
    except:
        return 'F'

def fetch_uaf_result(reg_no):
    try:
        session = requests.Session()
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Referer': 'https://lms.uaf.edu.pk/login/index.php',
        })

        # Step 1: Get login page for token & cookies
        login_url = 'https://lms.uaf.edu.pk/login/index.php'
        login_page = session.get(login_url, timeout=20, verify=False)
        soup = BeautifulSoup(login_page.text, 'html.parser')

        # Get token from result form
        token_input = soup.find('input', {'name': 'token'})
        token = token_input['value'] if token_input else ''

        # Step 2: Submit to correct URL with correct field name
        result_url = 'https://lms.uaf.edu.pk/course/uaf_student_result.php'
        data = {
            'REG': reg_no,
            'token': token,
        }

        result_resp = session.post(result_url, data=data, timeout=20, verify=False)
        result_soup = BeautifulSoup(result_resp.text, 'html.parser')

        # Step 3: Get student name
        student_name = reg_no.upper()
        for tag in ['h1','h2','h3','h4']:
            el = result_soup.find(tag)
            if el and el.get_text(strip=True):
                txt = el.get_text(strip=True)
                if len(txt) > 3 and 'uaf' not in txt.lower() and 'result' not in txt.lower():
                    student_name = txt
                    break

        # Step 4: Parse semester tables
        semesters = []
        tables = result_soup.find_all('table')

        for table in tables:
            rows = table.find_all('tr')
            if len(rows) < 2:
                continue

            # Get semester name from previous heading
            sem_name = 'Semester'
            prev = table.find_previous(['h1','h2','h3','h4','h5','h6','b','strong','th'])
            if prev:
                txt = prev.get_text(strip=True)
                if txt and len(txt) > 2:
                    sem_name = txt

            # Get header row to understand column positions
            header_row = rows[0]
            headers = [th.get_text(strip=True).lower() for th in header_row.find_all(['th','td'])]

            # Find column indexes
            name_idx = next((i for i,h in enumerate(headers) if 'course' in h or 'subject' in h or 'name' in h), 0)
            ch_idx = next((i for i,h in enumerate(headers) if 'hr' in h or 'hour' in h or 'credit' in h or 'ch' in h), 1)
            marks_idx = next((i for i,h in enumerate(headers) if 'mark' in h or 'obtain' in h or 'score' in h or 'total' in h), -1)
            grade_idx = next((i for i,h in enumerate(headers) if 'grade' in h), -1)
            gp_idx = next((i for i,h in enumerate(headers) if 'gp' in h or 'point' in h or 'quality' in h), -1)

            courses = []
            for row in rows[1:]:
                cells = row.find_all(['td','th'])
                if len(cells) < 2:
                    continue

                cell_texts = [c.get_text(strip=True) for c in cells]

                try:
                    course_name = cell_texts[name_idx] if name_idx < len(cell_texts) else ''
                    if not course_name or course_name.lower() in ['total','grand total','cgpa','gpa']:
                        continue

                    # Get credit hours
                    ch = 0
                    if ch_idx < len(cell_texts):
                        ch_text = cell_texts[ch_idx]
                        ch_match = re.search(r'\d+', ch_text)
                        if ch_match:
                            ch = int(ch_match.group())

                    if ch == 0 or ch > 6:
                        # Try to find CH from any cell
                        for txt in cell_texts[1:]:
                            m = re.match(r'^(\d)\(', txt)
                            if m:
                                ch = int(m.group(1))
                                break
                            elif re.match(r'^[1-6]$', txt.strip()):
                                ch = int(txt.strip())
                                break

                    # Get grade
                    grade = None
                    if grade_idx >= 0 and grade_idx < len(cell_texts):
                        g_text = cell_texts[grade_idx].strip()
                        if g_text in GRADE_POINTS:
                            grade = g_text

                    # Get marks
                    marks = None
                    if marks_idx >= 0 and marks_idx < len(cell_texts):
                        try:
                            marks = float(cell_texts[marks_idx])
                        except:
                            pass

                    # If no grade from column, derive from marks
                    if not grade and marks is not None:
                        grade = marks_to_grade(marks)

                    # If still no grade, scan all cells
                    if not grade:
                        for txt in cell_texts:
                            if txt.strip() in GRADE_POINTS:
                                grade = txt.strip()
                                break

                    if not grade:
                        continue

                    # Get quality points
                    qp = 0
                    if gp_idx >= 0 and gp_idx < len(cell_texts):
                        try:
                            qp = float(cell_texts[gp_idx])
                        except:
                            qp = round(GRADE_POINTS.get(grade, 0) * ch, 2)
                    else:
                        qp = round(GRADE_POINTS.get(grade, 0) * ch, 2)

                    if course_name and ch > 0 and grade:
                        courses.append({
                            'name': course_name,
                            'marks': marks,
                            'grade': grade,
                            'ch': ch,
                            'qp': qp
                        })
                except Exception as e:
                    continue

            if courses:
                sem_qp = sum(c['qp'] for c in courses)
                sem_ch = sum(c['ch'] for c in courses)
                sem_gpa = round(sem_qp / sem_ch, 2) if sem_ch > 0 else 0
                semesters.append({
                    'name': sem_name,
                    'courses': courses,
                    'gpa': sem_gpa,
                    'ch': sem_ch,
                    'percentage': round((sem_gpa / 4) * 100, 2)
                })

        if not semesters:
            # Return raw HTML snippet for debugging
            snippet = result_soup.get_text()[:500]
            return None, f"Could not parse result. Page content: {snippet}"

        total_qp = sum(s['gpa'] * s['ch'] for s in semesters)
        total_ch = sum(s['ch'] for s in semesters)
        cgpa = round(total_qp / total_ch, 2) if total_ch > 0 else 0

        return {
            'name': student_name,
            'reg_no': reg_no,
            'cgpa': cgpa,
            'percentage': round((cgpa / 4) * 100, 2),
            'total_ch': total_ch,
            'total_courses': sum(len(s['courses']) for s in semesters),
            'semesters': semesters
        }, None

    except requests.Timeout:
        return None, "Timeout — UAF server slow hai, dobara try karo"
    except Exception as e:
        return None, f"Error: {str(e)}"

@app.route('/')
def home():
    return jsonify({'status': 'UAF CGPA Calculator API Running', 'by': 'AS-ROHAIL'})

@app.route('/api/result', methods=['GET'])
def get_result():
    reg_no = request.args.get('reg', '').strip()
    if not reg_no:
        return jsonify({'success': False, 'error': 'Registration number required'}), 400
    if not re.match(r'^\d{4}-[a-zA-Z]+-\d+$', reg_no):
        return jsonify({'success': False, 'error': 'Invalid format. Use: 2024-ag-1234'}), 400
    data, error = fetch_uaf_result(reg_no)
    if error:
        return jsonify({'success': False, 'error': error}), 404
    return jsonify({'success': True, 'data': data})

@app.route('/api/debug', methods=['GET'])
def debug():
    try:
        session = requests.Session()
        session.headers.update({'User-Agent': 'Mozilla/5.0'})
        resp = session.get('https://lms.uaf.edu.pk/login/index.php', timeout=15, verify=False)
        soup = BeautifulSoup(resp.text, 'html.parser')
        forms = []
        for form in soup.find_all('form'):
            inputs = [{'name': i.get('name'), 'type': i.get('type'), 'id': i.get('id'), 'value': i.get('value','')} 
                     for i in form.find_all('input')]
            forms.append({'action': form.get('action'), 'id': form.get('id'), 'inputs': inputs})
        return jsonify({'status': resp.status_code, 'title': soup.title.string if soup.title else None, 'forms': forms})
    except Exception as e:
        return jsonify({'error': str(e)})

@app.route('/api/rawresult', methods=['GET'])
def raw_result():
    """Get raw HTML of result page for debugging"""
    reg_no = request.args.get('reg', '').strip()
    try:
        session = requests.Session()
        session.headers.update({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'})
        login_page = session.get('https://lms.uaf.edu.pk/login/index.php', timeout=15, verify=False)
        soup = BeautifulSoup(login_page.text, 'html.parser')
        token_input = soup.find('input', {'name': 'token'})
        token = token_input['value'] if token_input else ''
        result_url = 'https://lms.uaf.edu.pk/course/uaf_student_result.php'
        resp = session.post(result_url, data={'REG': reg_no, 'token': token}, timeout=20, verify=False)
        result_soup = BeautifulSoup(resp.text, 'html.parser')
        tables = result_soup.find_all('table')
        table_data = []
        for t in tables:
            rows = [[td.get_text(strip=True) for td in tr.find_all(['td','th'])] for tr in t.find_all('tr')]
            table_data.append(rows)
        return jsonify({'tables': table_data, 'text_snippet': result_soup.get_text()[:1000]})
    except Exception as e:
        return jsonify({'error': str(e)})

@app.route('/api/health')
def health():
    return jsonify({'status': 'ok'})

if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=5000)
