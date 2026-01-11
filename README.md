# Cerberus
*A Local-First Parental Monitoring System*

> **Protect what matters most — without sacrificing privacy.**  
> Cerberus continuously monitors a child’s screen for inappropriate content, saves full screenshots and cropped detections, and alerts parents in real time.  
> Everything runs **locally**, ensuring data never leaves your home network.

---

## Core Features
- **Continuous Screen Monitoring** – Detects NSFW or inappropriate images in real time.  
- **AI-Powered Detection** – Uses locally hosted models (PyTorch-based).  
- **Instant Alerts** – Sends notifications via **Discord Webhooks** (eventually be replaced with dedicated app).  
- **Local-Only Web Portal** – View events securely on your LAN (no cloud dependencies).  
- **Adjustable Sensitivity** – Tune model thresholds for stricter or more lenient detection.  
- **Client Connection Watchdog** – Detects if the monitored PC goes offline or disables monitoring.  

---

## System Architecture

### **Server**
- Hosts the NSFW detection models.  
- Stores screenshots, cropped detections, and event logs.  
- Sends notifications and serves the local web portal.  
- Can be run **headless** after initial setup.

### **Client**
- Installed on the monitored PC.  
- Captures screen images and securely transmits them to the local server.  

All communications are local and encrypted — nothing ever leaves your private network.

---

## Future Roadmap
| Feature | Description |
|:--|:--|
| **Interactive Learning** | Parents can mark detections as correct/incorrect to fine-tune the model. |
| **Text & Chat OCR** | Detect inappropriate or unsafe text on screen. |
| **App Control** | Identify and manage allowed or blocked applications. |
| **Mobile App (Android)** | Control and view logs from your phone. |
| **Audio/Voice Monitoring** | Detect suspicious voice chat or content via local transcription. |
| **Dynamic Slang Database** | Automatically update detection vocabularies for modern risks. |
| **Custom Linux ISO** | Simplified turnkey setup for the server. |

---

## Built With
- **Python 3.11+**  
- **PyTorch** – AI model inference  
- **OpenCV** – Image processing  
- **Flask** (planned) – Local web portal  
- **Discord Webhooks** – Real-time notifications  

---

## Supported Platforms
| Component | Windows | Linux | Android | macOS / iOS |
|:--|:--:|:--:|:--:|:--:|
| Server | ✅ | ✅ | ❌ | ⚙️ Manual only |
| Client | ✅ | ✅ | ❌ | ⚙️ Manual only |
| Web Portal | ✅ | ✅ | ✅ (app planned) | ⚙️ Manual only |

> Installers will be available for Windows and Linux.  
> Android app for the portal is planned once the base system stabilizes.

---

## Installation
> **Installers Coming Soon**

Cerberus will include graphical installers for Windows and Linux.  
Until then, developers can clone the repository and manually install dependencies:

```bash
git clone https://github.com/mdogdope/Cerberus.git
cd Cerberus
pip install -r requirements.txt
