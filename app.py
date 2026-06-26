from flask import Flask, jsonify, request
from flask_cors import CORS
import requests
from bs4 import BeautifulSoup
import re
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__)
CORS(app)

UAF_RESULT_URL = "https://lms.uaf.edu.pk/login/index.php"

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
        })

        # Get login page first for cookies
        login_page = session.get(UAF_RESULT_URL, timeout=15, verify=False)
        soup = BeautifulSoup(login_page.text, 'html.parser')

        # Get logintoken
        token_input = soup.find('input', {'name': 'logintoken'})
        logintoken = token_input['value'] if token_input else ''

        # Submit result form with reg number
        result_data = {
            'regNo': reg_no,
            'logintoken': logintoken
        }

        result_resp = session.post(UAF_RESULT_URL, data=result_data, timeout=15, verify=False)
        result_soup = BeautifulSoup(result_resp.text, 'html.parser')

        # Parse student name
        name_el = result_soup.find('h2') or result_soup.find(class_=re.compile(r'student.?name|name', re.I))
        student_name = name_el.get_text(strip=True) if name_el else reg_no.upper()

        # Parse semesters and courses
        semesters = []
        sem_blocks = result_soup.find_all(class_=re.compile(r'semester|sem', re.I)) or result_soup.find_all('table')

        if not sem_blocks:
            return None, "No result found for this registration number"

        for sem_block in sem_blocks:
            courses = []
            rows = sem_block.find_all('tr')
            sem_name = "Semester"

            # Try to get semester name
            sem_heading = sem_block.find_previous(re.compile(r'h[2-6]'))
            if sem_heading:
                sem_name = sem_heading.get_text(strip=True)

            for row in rows[1:]:  # Skip header
                cells = row.find_all('td')
                if len(cells) >= 3:
                    course_name = cells[0].get_text(strip=True)
                    marks_text = cells[-2].get_text(strip=True) if len(cells) > 2 else '0'
                    ch_text = cells[1].get_text(strip=True)

                    try:
                        marks = float(re.search(r'\d+\.?\d*', marks_text).group())
                        ch = float(re.search(r'\d+', ch_text).group())
                    except:
                        continue

                    if course_name and ch > 0:
                        grade = marks_to_grade(marks)
                        gp = GRADE_POINTS.get(grade, 0)
                        courses.append({
                            'name': course_name,
                            'marks': marks,
                            'grade': grade,
                            'ch': ch,
                            'qp': round(gp * ch, 2)
                        })

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
            return None, "Could not parse result data"

        # Calculate CGPA
        total_qp = sum(s['gpa'] * s['ch'] for s in semesters)
        total_ch = sum(s['ch'] for s in semesters)
        cgpa = round(total_qp / total_ch, 2) if total_ch > 0 else 0
        total_courses = sum(len(s['courses']) for s in semesters)

        return {
            'name': student_name,
            'reg_no': reg_no,
            'cgpa': cgpa,
            'percentage': round((cgpa / 4) * 100, 2),
            'total_ch': total_ch,
            'total_courses': total_courses,
            'semesters': semesters
        }, None

    except requests.Timeout:
        return None, "Request timeout - UAF server slow hai, dobara try karo"
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

    # Validate format: YYYY-xx-NNNN
    if not re.match(r'^\d{4}-[a-zA-Z]+-\d+$', reg_no):
        return jsonify({'success': False, 'error': 'Invalid format. Use: 2024-ag-1234'}), 400

    data, error = fetch_uaf_result(reg_no)

    if error:
        return jsonify({'success': False, 'error': error}), 404

    return jsonify({'success': True, 'data': data})

@app.route('/api/health')
def health():
    return jsonify({'status': 'ok', 'message': 'API is running'})

if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=5000)
