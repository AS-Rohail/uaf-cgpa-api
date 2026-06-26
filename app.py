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
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Referer': 'https://lms.uaf.edu.pk/login/index.php',
        }
        session.headers.update(headers)

        # Step 1: Get login page
        login_url = 'https://lms.uaf.edu.pk/login/index.php'
        login_page = session.get(login_url, timeout=20, verify=False)
        soup = BeautifulSoup(login_page.text, 'html.parser')

        # Debug: print page title
        print(f"Page title: {soup.title.string if soup.title else 'No title'}")

        # Step 2: Find all forms on page
        forms = soup.find_all('form')
        print(f"Found {len(forms)} forms")
        for i, form in enumerate(forms):
            print(f"Form {i}: action={form.get('action')}, id={form.get('id')}")
            inputs = form.find_all('input')
            for inp in inputs:
                print(f"  Input: name={inp.get('name')}, type={inp.get('type')}, id={inp.get('id')}")

        # Step 3: Try different field names for reg number
        # UAF might use different field names
        possible_fields = ['regNo', 'regno', 'reg_no', 'registration', 'username', 'reg', 'studentid', 'rollno']
        
        # Get logintoken
        token_input = soup.find('input', {'name': 'logintoken'})
        logintoken = token_input['value'] if token_input else ''

        result_html = None
        
        for field in possible_fields:
            try:
                data = {
                    field: reg_no,
                    'logintoken': logintoken,
                }
                resp = session.post(login_url, data=data, timeout=20, verify=False)
                if resp.status_code == 200 and len(resp.text) > 1000:
                    # Check if result data is in response
                    if any(word in resp.text.lower() for word in ['result', 'grade', 'gpa', 'course', 'semester', 'marks']):
                        print(f"Found result with field: {field}")
                        result_html = resp.text
                        break
            except Exception as e:
                print(f"Error with field {field}: {e}")
                continue

        # Step 4: Try GET request with reg number
        if not result_html:
            get_urls = [
                f'https://lms.uaf.edu.pk/login/index.php?regNo={reg_no}',
                f'https://lms.uaf.edu.pk/result/index.php?reg={reg_no}',
                f'https://lms.uaf.edu.pk/grade/report/index.php?reg={reg_no}',
            ]
            for url in get_urls:
                try:
                    resp = session.get(url, timeout=20, verify=False)
                    if resp.status_code == 200:
                        r_soup = BeautifulSoup(resp.text, 'html.parser')
                        tables = r_soup.find_all('table')
                        if tables:
                            print(f"Found tables at: {url}")
                            result_html = resp.text
                            break
                except:
                    continue

        if not result_html:
            # Return debug info
            return None, f"Could not fetch result. Page forms found: {len(forms)}. UAF LMS may have changed its structure."

        # Parse result
        result_soup = BeautifulSoup(result_html, 'html.parser')
        
        # Try to find student name
        student_name = reg_no.upper()
        name_patterns = [
            result_soup.find('h1'),
            result_soup.find('h2'),
            result_soup.find(class_=re.compile(r'name|student', re.I)),
            result_soup.find('td', string=re.compile(r'name', re.I)),
        ]
        for el in name_patterns:
            if el and el.get_text(strip=True) and len(el.get_text(strip=True)) > 3:
                student_name = el.get_text(strip=True)
                break

        # Parse tables for courses
        tables = result_soup.find_all('table')
        semesters = []
        
        for table in tables:
            rows = table.find_all('tr')
            if len(rows) < 2:
                continue
                
            courses = []
            sem_name = "Semester"
            
            # Check previous heading
            prev = table.find_previous(['h1','h2','h3','h4','h5','h6','strong','b'])
            if prev:
                sem_name = prev.get_text(strip=True)

            for row in rows[1:]:
                cells = row.find_all(['td','th'])
                if len(cells) < 2:
                    continue
                    
                cell_texts = [c.get_text(strip=True) for c in cells]
                
                # Try to find marks and credit hours
                marks = None
                ch = None
                course_name = cell_texts[0] if cell_texts else ''
                
                for text in cell_texts[1:]:
                    # Find credit hours (usually 1-6)
                    if re.match(r'^\d+(\(\d+-\d+\))?$', text):
                        num = int(re.search(r'\d+', text).group())
                        if 1 <= num <= 6 and ch is None:
                            ch = num
                    # Find marks (usually 0-100)
                    elif re.match(r'^\d+\.?\d*$', text):
                        num = float(text)
                        if 0 <= num <= 100 and marks is None:
                            marks = num

                if course_name and ch and marks is not None:
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
            return None, "Result page found but could not parse course data. UAF LMS structure may have changed."

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
    """Debug endpoint to see UAF LMS page structure"""
    try:
        session = requests.Session()
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        resp = session.get('https://lms.uaf.edu.pk/login/index.php', timeout=15, verify=False)
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        forms = []
        for form in soup.find_all('form'):
            inputs = [{'name': i.get('name'), 'type': i.get('type'), 'id': i.get('id')} 
                     for i in form.find_all('input')]
            forms.append({'action': form.get('action'), 'id': form.get('id'), 'inputs': inputs})
        
        return jsonify({
            'status': resp.status_code,
            'title': soup.title.string if soup.title else None,
            'forms': forms,
        })
    except Exception as e:
        return jsonify({'error': str(e)})

@app.route('/api/health')
def health():
    return jsonify({'status': 'ok'})

if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=5000)
