"""
UIT Survey Automation Tool - Enhanced Version
A PyQt5 application that automates the completion of online surveys for UIT students.
Enhanced with comprehensive question detection to avoid missing any questions.

Author: Hy
Version: 2.1 (Enhanced)
"""

import os
import sys
import threading
import time
import random
from typing import List, Dict, Optional

from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                           QLabel, QLineEdit, QPushButton, QTextEdit, QFrame, 
                           QStackedWidget, QMessageBox)
from PyQt5.QtGui import QPixmap, QFont, QIcon
from PyQt5.QtCore import Qt, QSize, pyqtSignal, QObject, QTimer

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.remote.webelement import WebElement
from selenium.common.exceptions import TimeoutException, NoSuchElementException

# Global state variables
paused = False
stop_thread = False
driver = None

def read_config(file_path: str) -> Dict[str, str]:
    """
    Read configuration from file.
    
    Args:
        file_path: Path to the configuration file
        
    Returns:
        Dictionary containing configuration key-value pairs
    """
    config = {}
    if os.path.exists(file_path):
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                for line in f:
                    if '=' in line:
                        key, value = line.strip().split('=', 1)
                        config[key] = value
        except Exception as e:
            print(f"Error reading config file: {e}")
    return config


def save_config_to_file(config: Dict[str, str], file_path: str) -> None:
    """
    Save configuration to file.
    
    Args:
        config: Dictionary containing configuration data
        file_path: Path where to save the configuration
    """
    try:
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, 'w', encoding='utf-8') as f:
            for k, v in config.items():
                f.write(f"{k}={v}\n")
    except Exception as e:
        print(f"Error saving config file: {e}")


def setup_edge_driver() -> Optional[webdriver.Edge]:
    """
    Setup and return Edge WebDriver with optimized options.
    
    Returns:
        WebDriver instance or None if setup fails
    """
    options = EdgeOptions()
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-extensions")
    options.add_argument("--log-level=3")
    options.add_argument("--inprivate")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)
    
    try:
        driver = webdriver.Edge(options=options)
        driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        driver.set_page_load_timeout(180)
        # Small delay for stabilization - GIẢM DELAY
        time.sleep(1)  # Giảm từ 2s xuống 1s để tăng tốc khởi tạo
        return driver
    except Exception as e:
        print(f"Error setting up Edge driver: {e}")
        return None


def find_and_select_comprehensive_questions(driver: webdriver.Edge, log_callback) -> bool:
    """
    Tìm và chọn tất cả câu hỏi bắt buộc trên trang hiện tại với logic toàn diện.
    Cải thiện để chọn đáp án tích cực cho việc đánh giá giáo viên.
    
    Args:
        driver: WebDriver instance
        log_callback: Function to log messages
        
    Returns:
        True if all questions were handled, False otherwise
    """
    global paused, stop_thread
    
    try:
        # Wait for page to load completely
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
        
        # Kiểm tra pause ngay đầu
        while paused and not stop_thread:
            time.sleep(0.05)  # Giảm delay pause check
        
        if stop_thread:
            return False
        
        total_questions_handled = 0
        
        # Tìm tất cả radio button groups với nhiều cách khác nhau
        log_callback("Đang tìm kiếm tất cả radio button groups...")
        
        # Method 1: Tìm theo mandatory class
        mandatory_radio_groups = driver.find_elements(By.CSS_SELECTOR, ".form-radios.mandatory, .list-radio.mandatory")
        
        # Method 2: Tìm tất cả radio buttons và nhóm theo name
        all_radios = driver.find_elements(By.CSS_SELECTOR, "input[type='radio']")
        radio_groups_by_name = {}
        
        for radio in all_radios:
            name = radio.get_attribute('name')
            if name:
                if name not in radio_groups_by_name:
                    radio_groups_by_name[name] = []
                radio_groups_by_name[name].append(radio)
        
        log_callback(f"Tìm thấy {len(mandatory_radio_groups)} mandatory groups và {len(radio_groups_by_name)} radio groups theo tên.")
        
        def select_best_answer_for_group(radios, group_identifier=""):
            """
            Chọn đáp án tốt nhất cho một nhóm radio buttons dựa trên nội dung
            """
            try:
                if not radios:
                    return False
                
                # Bỏ qua nếu đã có selection
                if any(radio.is_selected() for radio in radios):
                    return True
                
                # Lấy available radios
                available_radios = [radio for radio in radios if radio.is_enabled() and radio.is_displayed()]
                if not available_radios:
                    return False
                
                # Tìm text của câu hỏi và tất cả labels để phân tích
                question_text = ""
                all_labels = []
                
                try:
                    # Tìm parent element chứa câu hỏi
                    first_radio = available_radios[0]
                    
                    # Thử nhiều cách để tìm câu hỏi
                    parents_to_try = [
                        first_radio.find_element(By.XPATH, "../../.."),
                        first_radio.find_element(By.XPATH, "../.."),
                        first_radio.find_element(By.XPATH, "..")
                    ]
                    
                    for parent in parents_to_try:
                        text = parent.text.lower()
                        if len(text) > len(question_text):
                            question_text = text
                        if len(text) > 20:  # Đủ dài để chứa câu hỏi
                            break
                            
                    # Lấy tất cả labels
                    for radio in available_radios:
                        try:
                            # Thử nhiều cách để tìm label
                            label_texts = []
                            
                            # Cách 1: Tìm label liên kết
                            try:
                                label = radio.find_element(By.XPATH, "following-sibling::label")
                                label_texts.append(label.text.strip())
                            except:
                                pass
                            
                            # Cách 2: Tìm label chứa radio
                            try:
                                label = radio.find_element(By.XPATH, "../label")
                                label_texts.append(label.text.strip())
                            except:
                                pass
                            
                            # Cách 3: Tìm text trong parent
                            try:
                                parent_text = radio.find_element(By.XPATH, "..").text.strip()
                                if parent_text and parent_text not in label_texts:
                                    label_texts.append(parent_text)
                            except:
                                pass
                            
                            # Lưu label tốt nhất
                            best_label = ""
                            for lt in label_texts:
                                if len(lt) > len(best_label) and len(lt) < 100:
                                    best_label = lt
                            
                            all_labels.append(best_label.lower())
                            
                        except:
                            all_labels.append("")
                            
                except Exception as e:
                    log_callback(f"Lỗi khi phân tích câu hỏi: {e}")
                
                log_callback(f"Phân tích: {question_text[:100]}...")
                log_callback(f"Options: {all_labels}")
                
                # Logic chọn đáp án thông minh dựa trên nội dung
                selected_radio = None
                reason = ""
                
                # 1. Câu hỏi về tỷ lệ thời gian lên lớp - CHỌN >80%
                if ("thời gian" in question_text and ("lên lớp" in question_text or "môn học" in question_text)) or \
                   any("%" in label for label in all_labels):
                    
                    for i, radio in enumerate(available_radios):
                        label = all_labels[i] if i < len(all_labels) else ""
                        if (">80%" in label or "trên 80%" in label or 
                            ("80" in label and "%" in label and ">" in label)):
                            selected_radio = radio
                            reason = f"Chọn '>80%' cho câu hỏi thời gian lên lớp"
                            break
                    
                    # Nếu không tìm được >80%, tìm option có % cao nhất
                    if not selected_radio:
                        max_percent = 0
                        for i, radio in enumerate(available_radios):
                            label = all_labels[i] if i < len(all_labels) else ""
                            # Tìm số % trong label
                            import re
                            percentages = re.findall(r'(\d+)%', label)
                            for pct in percentages:
                                if int(pct) > max_percent:
                                    max_percent = int(pct)
                                    selected_radio = radio
                                    reason = f"Chọn {pct}% (cao nhất available) cho thời gian lên lớp"
                
                # 2. Câu hỏi về % chuẩn đầu ra - CHỌN 70-90%
                elif ("chuẩn đầu ra" in question_text or "đạt được" in question_text) and "%" in question_text:
                    for i, radio in enumerate(available_radios):
                        label = all_labels[i] if i < len(all_labels) else ""
                        if (("70" in label and "90" in label) or 
                            ("từ 70" in label and "dưới 90" in label)):
                            selected_radio = radio
                            reason = f"Chọn 'Từ 70 đến dưới 90%' cho câu hỏi chuẩn đầu ra"
                            break
                    
                    # Fallback: chọn option có 70-90
                    if not selected_radio:
                        for i, radio in enumerate(available_radios):
                            label = all_labels[i] if i < len(all_labels) else ""
                            if "70" in label or "80" in label:
                                selected_radio = radio
                                reason = f"Chọn option chứa 70-80% cho chuẩn đầu ra"
                                break
                
                # 3. Câu hỏi đánh giá giáo viên (rating scale 1-4) - CHỌN 4
                elif ("đánh giá" in question_text or "giảng viên" in question_text or 
                      "giáo viên" in question_text or "hoạt động giảng dạy" in question_text or 
                      "phương pháp" in question_text or "moodle" in question_text or
                      len([l for l in all_labels if any(kw in l for kw in ["1", "2", "3", "4"])]) >= 3):
                    
                    # Tìm option có value cao nhất (thường là 4)
                    max_value = 0
                    for radio in available_radios:
                        try:
                            value = radio.get_attribute('value')
                            if value and value.isdigit():
                                val = int(value)
                                if val > max_value:
                                    max_value = val
                                    selected_radio = radio
                                    reason = f"Chọn option {val} (cao nhất) cho đánh giá giảng viên"
                        except:
                            continue
                    
                    # Nếu không có value, chọn option cuối cùng (thường là tốt nhất)
                    if not selected_radio:
                        selected_radio = available_radios[-1]
                        reason = f"Chọn option cuối cùng (tích cực nhất) cho đánh giá"
                
                # 4. Các câu hỏi khác - chọn option tích cực nhất
                else:
                    # Tìm các từ khóa tích cực trong labels
                    positive_keywords = ["rất", "tốt", "hài lòng", "đồng ý", "cao", "nhiều", "4"]
                    
                    for i, radio in enumerate(available_radios):
                        label = all_labels[i] if i < len(all_labels) else ""
                        if any(keyword in label for keyword in positive_keywords):
                            selected_radio = radio
                            reason = f"Chọn option tích cực: {label[:30]}"
                            break
                    
                    # Nếu không tìm được từ khóa tích cực, chọn theo value cao nhất
                    if not selected_radio:
                        max_value = 0
                        for radio in available_radios:
                            try:
                                value = radio.get_attribute('value')
                                if value and value.isdigit():
                                    val = int(value)
                                    if val > max_value:
                                        max_value = val
                                        selected_radio = radio
                                        reason = f"Chọn value cao nhất: {val}"
                            except:
                                continue
                    
                    # Fallback: chọn option cuối cùng
                    if not selected_radio:
                        selected_radio = available_radios[-1]
                        reason = "Chọn option cuối cùng (fallback)"
                
                # Thực hiện click
                if selected_radio:
                    driver.execute_script("arguments[0].click();", selected_radio)
                    log_callback(f"✓ {reason}")
                    return True
                else:
                    # Fallback cuối cùng - chọn option cuối cùng thay vì đầu tiên
                    driver.execute_script("arguments[0].click();", available_radios[-1])
                    log_callback(f"⚠ Chọn option cuối cùng (fallback) cho group {group_identifier}")
                    return True
                    
            except Exception as e:
                log_callback(f"Lỗi khi xử lý group {group_identifier}: {e}")
                return False
        
        # Xử lý mandatory radio groups trước
        for i, group in enumerate(mandatory_radio_groups):
            try:
                radio_buttons = group.find_elements(By.CSS_SELECTOR, "input[type='radio']")
                
                if not radio_buttons:
                    continue
                
                if select_best_answer_for_group(radio_buttons, f"mandatory-{i+1}"):
                    total_questions_handled += 1
                    
            except Exception as e:
                log_callback(f"Lỗi khi xử lý mandatory group {i+1}: {e}")
                continue
        
        # Xử lý các radio groups còn lại theo tên
        for name, radios in radio_groups_by_name.items():
            try:
                # Bỏ qua nếu đã có selection
                if any(radio.is_selected() for radio in radios):
                    continue
                
                if select_best_answer_for_group(radios, f"named-{name}"):
                    total_questions_handled += 1
                    
            except Exception as e:
                log_callback(f"Lỗi khi xử lý radio group '{name}': {e}")
                continue
        
        # Xử lý select dropdowns
        log_callback("Đang tìm kiếm select dropdowns...")
        select_elements = driver.find_elements(By.CSS_SELECTOR, "select")
        
        for i, select in enumerate(select_elements):
            try:
                if select.get_attribute("disabled") or not select.is_displayed():
                    continue
                    
                options = select.find_elements(By.CSS_SELECTOR, "option")
                if len(options) > 1:  # Có options để chọn
                    current_value = select.get_attribute("value")
                    if not current_value or current_value == options[0].get_attribute("value"):
                        # Chọn option tích cực nhất (thường là cuối cùng)
                        best_option_index = len(options) - 1
                        driver.execute_script(f"arguments[0].selectedIndex = {best_option_index}; arguments[0].dispatchEvent(new Event('change'));", select)
                        log_callback(f"Đã chọn option tích cực nhất cho select dropdown {i+1}")
                        total_questions_handled += 1
                        
            except Exception as e:
                log_callback(f"Lỗi khi xử lý select {i+1}: {e}")
                continue
        
        # Xử lý text inputs và textareas (nếu bắt buộc)
        text_inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='text'], textarea")
        
        for i, input_elem in enumerate(text_inputs):
            try:
                input_class = input_elem.get_attribute("class") or ""
                if (input_elem.get_attribute("required") or "mandatory" in input_class):
                    current_value = input_elem.get_attribute("value")
                    if not current_value or current_value.strip() == "":
                        # Điền text tích cực
                        input_elem.clear()
                        input_elem.send_keys("Rất hài lòng với chất lượng giảng dạy")
                        log_callback(f"Đã điền feedback tích cực cho input bắt buộc {i+1}")
                        total_questions_handled += 1
                        
            except Exception as e:
                log_callback(f"Lỗi khi xử lý text input {i+1}: {e}")
                continue
        
        log_callback(f"✅ Đã xử lý tổng cộng {total_questions_handled} câu hỏi/thành phần với logic đánh giá tích cực.")
        return True
        
    except Exception as e:
        log_callback(f"Lỗi trong find_and_select_comprehensive_questions: {e}")
        return False


def wait_for_element_and_click(driver: webdriver.Edge, locator: tuple, timeout: int = 10) -> bool:
    """
    Wait for an element to be clickable and click it.
    
    Args:
        driver: WebDriver instance
        locator: Tuple of (By.TYPE, value)
        timeout: Maximum time to wait in seconds
        
    Returns:
        True if element was clicked successfully, False otherwise
    """
    try:
        element = WebDriverWait(driver, timeout).until(
            EC.element_to_be_clickable(locator)
        )
        element.click()
        return True
    except TimeoutException:
        return False
    except Exception:
        return False

def survey_main(config: Dict[str, str], log_callback, status_callback) -> None:
    """
    Main survey automation function with improved reliability and UX.
    
    Args:
        config: Configuration dictionary containing email and password
        log_callback: Function to log messages
        status_callback: Function to update status
    """
    global paused, stop_thread, driver
    
    survey_url = 'https://student.uit.edu.vn/sinhvien/phieukhaosat'
    email = config.get('email', '')
    password = config.get('password', '')
    
    if not email or not password:
        log_callback("[ERROR] Email hoặc mật khẩu không được để trống!")
        status_callback("Lỗi: Thiếu thông tin đăng nhập")
        return
    
    # Initialize browser
    status_callback("Đang khởi tạo trình duyệt...")
    log_callback("Khởi tạo trình duyệt Edge...")
    
    driver = setup_edge_driver()
    if not driver:
        log_callback("[ERROR] Không thể khởi tạo trình duyệt Edge!")
        log_callback("Vui lòng kiểm tra lại Microsoft Edge và Edge WebDriver")
        status_callback("Lỗi: Không thể khởi tạo trình duyệt")
        return
    
    try:
        # Navigate to survey page
        status_callback("Đang mở trang khảo sát...")
        log_callback("Đang mở trang khảo sát...")
        driver.get(survey_url)
        
        # Fill login information
        status_callback("Đang điền thông tin đăng nhập...")
        log_callback("Đang điền thông tin đăng nhập...")
        
        try:
            email_field = WebDriverWait(driver, 30).until(
                EC.presence_of_element_located((By.NAME, "name"))
            )
            password_field = driver.find_element(By.NAME, "pass")
            
            email_field.clear()
            email_field.send_keys(email)
            password_field.clear()
            password_field.send_keys(password)
            
            log_callback("Đã điền thông tin đăng nhập.")
            
        except TimeoutException:
            log_callback("[ERROR] Không tìm thấy form đăng nhập!")
            status_callback("Lỗi: Không tìm thấy form đăng nhập")
            return
        
        # Show login completion dialog
        status_callback("Chờ hoàn tất đăng nhập...")
        log_callback("@SHOW_LOGIN_MESSAGE@")
        
        # After user completes login, continue with survey processing
        status_callback("Đang tìm kiếm khảo sát...")
        log_callback("Đang lấy danh sách khảo sát chưa thực hiện...")
        
        # Get survey list with retry mechanism
        survey_links = []
        max_retries = 3
        for attempt in range(max_retries):
            try:
                # Wait for the survey table to load
                WebDriverWait(driver, 20).until(
                    EC.presence_of_element_located((By.XPATH, "//*[@id='block-system-main']/div/table/tbody"))
                )
                
                rows = driver.find_elements(By.XPATH, "//*[@id='block-system-main']/div/table/tbody/tr")
                survey_links = []
                
                for row in rows:
                    try:
                        survey_link = row.find_element(By.XPATH, "./td[2]/strong/a").get_attribute("href")
                        status_element = row.find_element(By.XPATH, "./td[3]")
                        status = status_element.text.strip()
                        
                        if status == "(Chưa khảo sát)":
                            survey_links.append(survey_link)
                            
                    except (NoSuchElementException, Exception):
                        continue
                        
                break  # Success, exit retry loop
                
            except TimeoutException:
                if attempt < max_retries - 1:
                    log_callback(f"Thử lại lần {attempt + 2}/{max_retries}...")
                    time.sleep(2)
                else:
                    log_callback("[ERROR] Không thể tải danh sách khảo sát!")
                    status_callback("Lỗi: Không thể tải danh sách khảo sát")
                    return
        
        if not survey_links:
            log_callback("Không có khảo sát nào cần thực hiện.")
            status_callback("Hoàn thành: Không có khảo sát nào cần làm")
            return
            
        log_callback(f"Tìm thấy {len(survey_links)} khảo sát chưa thực hiện.")
        
        # Process each survey
        for index, survey_link in enumerate(survey_links):
            if stop_thread:
                status_callback("Đã dừng")
                break
                
            current_survey = index + 1
            total_surveys = len(survey_links)
            
            status_callback(f"Đang làm khảo sát {current_survey}/{total_surveys}")
            log_callback(f"Đang thực hiện khảo sát {current_survey}/{total_surveys}: {survey_link}")
            
            try:
                # Navigate to survey
                driver.get(survey_link)
                
                # Process survey pages
                page_count = 0
                max_pages = 10  # Safety limit to prevent infinite loops
                
                while page_count < max_pages:
                    if stop_thread:
                        break
                        
                    # Handle pause state - KIỂM TRA PAUSE NHIỀU LẦN HỖN
                    while paused and not stop_thread:
                        time.sleep(0.05)  # Giảm từ 0.1 xuống 0.05 để responsive hơn
                        # Update status khi đang pause
                        status_callback("Đã tạm dừng - Nhấn 'Tiếp tục' để tiếp tục")
                    
                    if stop_thread:
                        break
                    
                    page_count += 1
                    log_callback(f"Đang xử lý trang {page_count} của khảo sát {current_survey}")
                    
                    # KIỂM TRA PAUSE TRƯỚC KHI XỬ LÝ CÂU HỎI
                    while paused and not stop_thread:
                        time.sleep(0.05)  # Giảm delay pause check
                        status_callback("Đã tạm dừng - Nhấn 'Tiếp tục' để tiếp tục")
                    
                    if stop_thread:
                        break
                    
                    # Handle mandatory questions on current page
                    if not find_and_select_comprehensive_questions(driver, log_callback):
                        log_callback(f"[WARNING] Không thể trả lời tất cả câu hỏi bắt buộc ở trang {page_count}")
                    
                    # KIỂM TRA PAUSE TRƯỚC KHI CHUYỂN TRANG
                    while paused and not stop_thread:
                        time.sleep(0.05)  # Giảm delay pause check
                        status_callback("Đã tạm dừng - Nhấn 'Tiếp tục' để tiếp tục")
                    
                    if stop_thread:
                        break
                    
                    # Try to click next button
                    if wait_for_element_and_click(driver, (By.ID, "movenextbtn"), timeout=5):
                        log_callback(f"Đã chuyển sang trang tiếp theo (trang {page_count + 1})")
                        # Wait for page transition - GIẢM DELAY
                        time.sleep(0.5)  # Giảm từ 1s xuống 0.5s để tăng tốc
                    else:
                        # No more next button, try to submit
                        log_callback("Không tìm thấy nút 'Tiếp theo', thử gửi khảo sát...")
                        break
                
                # Submit the survey
                if wait_for_element_and_click(driver, (By.ID, "movesubmitbtn"), timeout=10):
                    log_callback(f"Đã gửi khảo sát {current_survey} thành công!")
                    
                    # Wait for submission to complete - GIẢM DELAY
                    time.sleep(1)  # Giảm từ 2s xuống 1s để tăng tốc
                    
                    # Return to main survey page
                    driver.get(survey_url)
                    log_callback(f"Khảo sát {current_survey} hoàn thành, đã quay lại trang chính.")
                    
                else:
                    log_callback(f"[ERROR] Không thể gửi khảo sát {current_survey}")
                    
            except Exception as e:
                log_callback(f"[ERROR] Lỗi khi xử lý khảo sát {current_survey}: {e}")
                continue
        
        if not stop_thread:
            log_callback("Hoàn thành tất cả khảo sát!")
            status_callback("Hoàn thành tất cả khảo sát!")
        
    except Exception as e:
        log_callback(f"[ERROR] Lỗi không mong muốn: {e}")
        status_callback("Lỗi: Đã xảy ra lỗi không mong muốn")
        
    finally:
        if driver:
            try:
                driver.quit()
                log_callback("[INFO] Đã đóng trình duyệt.")
            except Exception:
                pass


class LogSignal(QObject):
    """Signal class for thread-safe logging."""
    signal = pyqtSignal(str)


class StatusSignal(QObject):
    """Signal class for thread-safe status updates."""
    signal = pyqtSignal(str)


class App(QMainWindow):
    """
    Main application class with improved UX and reliability.
    
    Key improvements:
    - Streamlined login flow
    - Real-time status updates
    - Better error handling
    - Cleaner UI design
    """
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Tool Khảo Sát UIT - By Hy (v2.1 Enhanced)")
        self.setWindowIcon(QIcon("uit_logo.png"))
        self.setGeometry(100, 100, 900, 750)
        
        # Apply modern dark theme
        self.setStyleSheet("""
            QMainWindow {
                background-color: #1e1e2e;
                color: #cdd6f4;
            }
            QLabel {
                color: #cdd6f4;
                font-size: 14px;
            }
            QLabel#status_label {
                color: #89b4fa;
                font-size: 16px;
                font-weight: bold;
                background-color: #313244;
                border: 2px solid #45475a;
                border-radius: 8px;
                padding: 12px;
                margin: 10px 0;
            }
            QLineEdit {
                background-color: #313244;
                color: #cdd6f4;
                border: 1px solid #45475a;
                border-radius: 5px;
                padding: 8px;
                font-size: 14px;
            }
            QLineEdit:focus {
                border: 2px solid #89b4fa;
            }
            QPushButton {
                background-color: #7287fd;
                color: #ffffff;
                border: none;
                border-radius: 5px;
                padding: 10px 15px;
                font-weight: bold;
                font-size: 14px;
                min-width: 100px;
            }
            QPushButton:hover {
                background-color: #89b4fa;
            }
            QPushButton:pressed {
                background-color: #6c7dd1;
            }
            QPushButton:disabled {
                background-color: #45475a;
                color: #6c6f85;
            }
            QTextEdit {
                background-color: #313244;
                color: #cdd6f4;
                border: 1px solid #45475a;
                border-radius: 5px;
                font-family: 'Consolas', 'Monaco', monospace;
                font-size: 13px;
                line-height: 1.4;
            }
            QFrame#form_frame {
                background-color: #181825;
                border: 1px solid #45475a;
                border-radius: 10px;
                padding: 20px;
            }
            QMessageBox {
                background-color: #1e1e2e;
                color: #cdd6f4;
            }
            QMessageBox QPushButton {
                background-color: #7287fd;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 8px 16px;
                font-weight: bold;
            }
        """)
        
        # Create stacked widget for multiple screens
        self.stacked_widget = QStackedWidget()
        self.setCentralWidget(self.stacked_widget)
        
        # Setup config directory
        config_dir = os.path.join(os.path.expanduser("~"), ".tool_khaosat")
        if not os.path.exists(config_dir):
            os.makedirs(config_dir)
        self.config_file_path = os.path.join(config_dir, "config.txt")
        
        # Create login page and survey page
        self.create_login_page()
        self.create_survey_page()
        
        # Load existing configuration
        self.load_existing_config()
        
        # Setup signal connections for thread-safe operations
        self.log_signal = LogSignal()
        self.log_signal.signal.connect(self.update_log)
        self.status_signal = StatusSignal()
        self.status_signal.signal.connect(self.update_status_label)
        
        # Timer for periodic UI updates
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.periodic_update)
        self.update_timer.start(1000)  # Update every second
        
    def create_login_page(self) -> None:
        """Create the improved login page with streamlined UX."""
        login_widget = QWidget()
        login_layout = QVBoxLayout()
        login_layout.setSpacing(20)
        login_layout.setContentsMargins(40, 40, 40, 40)
        
        # Logo section
        logo_frame = QFrame()
        logo_layout = QVBoxLayout(logo_frame)
        logo_label = QLabel()
        
        # Try to load the logo
        try:
            base_path = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
            logo_path = os.path.join(base_path, "uit_logo.png")
            if os.path.exists(logo_path):
                pixmap = QPixmap(logo_path)
                logo_label.setPixmap(pixmap.scaled(150, 150, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            else:
                raise FileNotFoundError("Logo file not found")
        except Exception as e:
            # Create a text-based logo if image fails to load
            logo_label.setText("🎓 UIT")
            logo_label.setAlignment(Qt.AlignCenter)
            logo_label.setStyleSheet("font-size: 48px; font-weight: bold; color: #89b4fa;")
        
        logo_label.setAlignment(Qt.AlignCenter)
        logo_layout.addWidget(logo_label)
        logo_layout.setAlignment(Qt.AlignCenter)
        login_layout.addWidget(logo_frame)
        
        # Title section
        title_label = QLabel("Tool Khảo Sát UIT")
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet("""
            font-size: 28px; 
            font-weight: bold; 
            color: #89b4fa; 
            margin: 10px 0 30px 0;
        """)
        login_layout.addWidget(title_label)
        
        # Subtitle
        subtitle_label = QLabel("Tự động hóa việc thực hiện khảo sát cho sinh viên UIT")
        subtitle_label.setAlignment(Qt.AlignCenter)
        subtitle_label.setStyleSheet("font-size: 14px; color: #a6adc8; margin-bottom: 20px;")
        login_layout.addWidget(subtitle_label)
        
        # Form container with enhanced styling
        form_frame = QFrame()
        form_frame.setObjectName("form_frame")
        form_layout = QVBoxLayout(form_frame)
        form_layout.setSpacing(15)
        form_layout.setContentsMargins(30, 30, 30, 30)
        
        # Student ID input section
        id_label = QLabel("📧 Mã số sinh viên:")
        id_label.setStyleSheet("font-weight: bold; color: #cdd6f4; margin-bottom: 5px;")
        self.id_input = QLineEdit()
        self.id_input.setPlaceholderText("Nhập MSSV của bạn...")
        self.id_input.setMinimumHeight(45)
        
        # Password input section
        password_label = QLabel("🔒 Mật khẩu:")
        password_label.setStyleSheet("font-weight: bold; color: #cdd6f4; margin-bottom: 5px;")
        self.password_input = QLineEdit()
        self.password_input.setPlaceholderText("Nhập mật khẩu của bạn...")
        self.password_input.setEchoMode(QLineEdit.Password)
        self.password_input.setMinimumHeight(45)
        
        # Add Enter key support
        self.password_input.returnPressed.connect(self.start_tool)
        
        # Add form elements
        form_layout.addWidget(id_label)
        form_layout.addWidget(self.id_input)
        form_layout.addWidget(password_label)
        form_layout.addWidget(self.password_input)
        
        # Buttons container with improved layout
        button_frame = QFrame()
        button_layout = QHBoxLayout(button_frame)
        button_layout.setSpacing(15)
        
        # Action buttons with enhanced styling
        save_button = QPushButton("💾 Lưu cấu hình")
        save_button.clicked.connect(self.save_config)
        save_button.setFixedSize(150, 45)
        save_button.setToolTip("Lưu thông tin đăng nhập để sử dụng lần sau")
        
        start_button = QPushButton("🚀 Bắt đầu")
        start_button.clicked.connect(self.start_tool)
        start_button.setFixedSize(150, 45)
        start_button.setStyleSheet("""
            QPushButton {
                background-color: #a6e3a1;
                color: #1e1e2e;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #b9e9b6;
            }
            QPushButton:pressed {
                background-color: #93d393;
            }
        """)
        start_button.setToolTip("Bắt đầu quá trình tự động thực hiện khảo sát")
        
        exit_button = QPushButton("❌ Thoát")
        exit_button.clicked.connect(self.exit_tool)
        exit_button.setFixedSize(150, 45)
        exit_button.setStyleSheet("""
            QPushButton {
                background-color: #f38ba8;
                color: #1e1e2e;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #f5a3bd;
            }
            QPushButton:pressed {
                background-color: #f07a9d;
            }
        """)
        exit_button.setToolTip("Thoát ứng dụng")
        
        button_layout.addWidget(save_button)
        button_layout.addWidget(start_button)
        button_layout.addWidget(exit_button)
        button_layout.setAlignment(Qt.AlignCenter)
        
        # Add buttons to form
        form_layout.addSpacing(20)
        form_layout.addWidget(button_frame)
        
        # Add form to main layout
        login_layout.addWidget(form_frame)
        login_layout.addStretch()
        
        # Footer
        footer_label = QLabel("Version 2.1 - Nâng cao độ tin cậy và phát hiện câu hỏi toàn diện")
        footer_label.setAlignment(Qt.AlignCenter)
        footer_label.setStyleSheet("color: #6c6f85; font-size: 12px; margin-top: 20px;")
        login_layout.addWidget(footer_label)
        login_widget.setLayout(login_layout)
        self.stacked_widget.addWidget(login_widget)
        
    def create_survey_page(self) -> None:
        """Create the improved survey page with status updates and streamlined controls."""
        survey_widget = QWidget()
        survey_layout = QVBoxLayout()
        survey_layout.setSpacing(15)
        survey_layout.setContentsMargins(20, 20, 20, 20)
        
        # Title section
        title_label = QLabel("Khảo Sát UIT - Đang thực hiện")
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet("""
            font-size: 26px; 
            font-weight: bold; 
            color: #89b4fa; 
            margin: 10px 0;
        """)
        survey_layout.addWidget(title_label)
        
        # Status label - NEW FEATURE for real-time status updates
        self.status_label = QLabel("Đang chuẩn bị...")
        self.status_label.setObjectName("status_label")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setWordWrap(True)
        survey_layout.addWidget(self.status_label)
        
        # Log text area with enhanced styling
        log_label = QLabel("📝 Nhật ký hoạt động:")
        log_label.setStyleSheet("font-weight: bold; color: #cdd6f4; margin-bottom: 5px;")
        survey_layout.addWidget(log_label)
        
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMinimumHeight(300)
        self.log_text.setStyleSheet("""
            QTextEdit {
                background-color: #313244;
                color: #cdd6f4;
                border: 1px solid #45475a;
                border-radius: 8px;
                font-family: 'Consolas', 'Monaco', monospace;
                font-size: 13px;
                line-height: 1.5;
                padding: 10px;
            }
        """)
        survey_layout.addWidget(self.log_text, 1)
        
        # Control buttons with improved layout
        button_frame = QFrame()
        button_layout = QHBoxLayout(button_frame)
        button_layout.setSpacing(15)
        
        # Pause/Resume button
        self.pause_button = QPushButton("⏸️ Tạm dừng")
        self.pause_button.clicked.connect(self.toggle_pause)
        self.pause_button.setFixedSize(140, 45)
        self.pause_button.setToolTip("Tạm dừng hoặc tiếp tục quá trình thực hiện khảo sát")
        
        # Back to config button
        config_button = QPushButton("⚙️ Cấu hình")
        config_button.clicked.connect(self.show_config_frame)
        config_button.setFixedSize(140, 45)
        config_button.setToolTip("Quay lại trang cấu hình để thay đổi thông tin đăng nhập")
        
        # Exit button
        exit_button = QPushButton("🚪 Thoát")
        exit_button.clicked.connect(self.exit_tool)
        exit_button.setFixedSize(140, 45)
        exit_button.setStyleSheet("""
            QPushButton {
                background-color: #f38ba8;
                color: #1e1e2e;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #f5a3bd;
            }
            QPushButton:pressed {
                background-color: #f07a9d;
            }
        """)
        exit_button.setToolTip("Thoát ứng dụng")
        
        button_layout.addWidget(self.pause_button)
        button_layout.addWidget(config_button)
        button_layout.addWidget(exit_button)
        button_layout.setAlignment(Qt.AlignCenter)
        survey_layout.addWidget(button_frame)
        survey_widget.setLayout(survey_layout)
        self.stacked_widget.addWidget(survey_widget)
        
    def load_existing_config(self) -> None:
        """Load existing configuration from file."""
        config = read_config(self.config_file_path)
        if config:
            self.id_input.setText(config.get("email", ""))
            self.password_input.setText(config.get("password", ""))
            
    def save_config(self) -> None:
        """Save current configuration to file."""
        cfg = {
            "email": self.id_input.text().strip(),
            "password": self.password_input.text().strip()
        }
        
        if not cfg["email"] or not cfg["password"]:
            QMessageBox.warning(self, "Thiếu thông tin", 
                              "Vui lòng nhập đầy đủ MSSV và mật khẩu!")
            return
            
        save_config_to_file(cfg, self.config_file_path)
        QMessageBox.information(self, "Thành công", "Đã lưu cấu hình thành công!")
        
    def start_tool(self) -> None:
        """Start the survey automation process with improved workflow."""
        # Validate input fields
        if not self.id_input.text().strip() or not self.password_input.text().strip():
            QMessageBox.warning(self, "Thiếu thông tin", 
                              "Vui lòng nhập đầy đủ MSSV và mật khẩu!")
            return
        
        # Save config first
        self.save_config()
        
        # Switch to survey page
        self.stacked_widget.setCurrentIndex(1)
        
        # Reset global states
        global stop_thread, paused
        stop_thread = False
        paused = False
        
        # Update status
        self.update_status("Đang chuẩn bị...")
        
        # Load config
        config = read_config(self.config_file_path)
        
        # Start survey thread with both log and status callbacks
        self.log("🚀 Khởi động công cụ tự động khảo sát UIT v2.1...")
        threading.Thread(
            target=survey_main, 
            args=(config, self.log, self.update_status), 
            daemon=True
        ).start()
        
    def log(self, msg: str) -> None:
        """Thread-safe logging method."""
        self.log_signal.signal.emit(msg)
        
    def update_status(self, status: str) -> None:
        """Thread-safe status update method."""
        self.status_signal.signal.emit(status)
        
    def update_log(self, msg: str) -> None:
        """Handle log message updates in the main thread."""
        if msg == "@SHOW_LOGIN_MESSAGE@":
            # Show streamlined login completion dialog
            msgBox = QMessageBox(self)
            msgBox.setIcon(QMessageBox.Information)
            msgBox.setWindowTitle("Hoàn tất đăng nhập")
            msgBox.setText("Vui lòng hoàn tất đăng nhập (nhập CAPTCHA nếu có),\nrồi nhấn OK để bắt đầu tự động thực hiện khảo sát.")
            msgBox.setStandardButtons(QMessageBox.Ok)
            
            # Apply custom styling to message box
            msgBox.setStyleSheet("""
                QMessageBox {
                    background-color: #1e1e2e;
                    color: #cdd6f4;
                }
                QMessageBox QLabel {
                    color: #cdd6f4;
                    font-size: 14px;
                }
                QMessageBox QPushButton {
                    background-color: #a6e3a1;
                    color: #1e1e2e;
                    border: none;
                    border-radius: 4px;
                    padding: 8px 16px;
                    font-weight: bold;
                    min-width: 80px;
                }
            """)
            
            msgBox.exec_()
        else:
            # Add timestamp to log messages
            import datetime
            timestamp = datetime.datetime.now().strftime("%H:%M:%S")
            formatted_msg = f"[{timestamp}] {msg}"
            
            self.log_text.append(formatted_msg)
            
            # Auto scroll to bottom
            cursor = self.log_text.textCursor()
            cursor.movePosition(cursor.End)
            self.log_text.setTextCursor(cursor)
            
    def update_status_label(self, status: str) -> None:
        """Update the status label in the main thread."""
        if hasattr(self, 'status_label'):
            self.status_label.setText(status)
            
    def toggle_pause(self) -> None:
        """Toggle pause/resume functionality with improved UX."""
        global paused
        
        if paused:
            paused = False
            self.pause_button.setText("⏸️ Tạm dừng")
            self.pause_button.setStyleSheet("")  # Reset to default style
            self.log("▶️ Tiếp tục thực hiện khảo sát...")
            self.update_status("Đang tiếp tục...")
        else:
            paused = True
            self.pause_button.setText("▶️ Tiếp tục")
            self.pause_button.setStyleSheet("""
                QPushButton {
                    background-color: #a6e3a1;
                    color: #1e1e2e;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #b9e9b6;
                }
            """)
            self.log("⏸️ Đã tạm dừng quá trình thực hiện.")
            self.update_status("Đã tạm dừng")
        
    def show_config_frame(self) -> None:
        """Return to configuration page."""
        global stop_thread
        
        reply = QMessageBox.question(
            self, 
            "Quay lại cấu hình", 
            "Bạn có muốn dừng quá trình hiện tại và quay lại trang cấu hình?", 
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            stop_thread = True
            self.stacked_widget.setCurrentIndex(0)
            self.log("🔄 Đã quay lại trang cấu hình.")
            
    def periodic_update(self) -> None:
        """Periodic UI updates."""
        # This method can be used for any periodic UI updates if needed
        pass
        
    def exit_tool(self) -> None:
        """Exit the application with proper cleanup."""
        global stop_thread, driver
        
        reply = QMessageBox.question(
            self, 
            "Xác nhận thoát", 
            "Bạn có chắc chắn muốn thoát ứng dụng?\nMọi tiến trình đang chạy sẽ bị dừng.", 
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            stop_thread = True
            
            # Try to close browser gracefully
            if driver:
                try:
                    driver.quit()
                    self.log("🌐 Đã đóng trình duyệt.")
                except Exception:
                    pass
                    
            self.log("👋 Cảm ơn bạn đã sử dụng Tool Khảo Sát UIT!")
            self.close()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = App()
    window.show()
    sys.exit(app.exec_()) 