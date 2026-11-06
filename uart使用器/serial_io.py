import queue
import threading
import tkinter as tk
from datetime import datetime
from tkinter import messagebox

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    serial = None
    list_ports = None


class SerialMixin:
    def refresh(self):
        if list_ports is None:
            self.ports["values"] = ()
            self.status.set("尚未安装 pyserial")
            return

        previous_device = self.port_map.get(self.portname.get())
        previous_devices=set(self.port_map.values())
        ports = list(list_ports.comports())

        def is_bluetooth(p):
            details = f"{p.description or ''} {p.hwid or ''}".lower()
            return "bthenum" in details or "bluetooth" in details or "蓝牙" in details

        def is_usb_serial(p):
            if is_bluetooth(p):
                return False
            details = f"{p.description or ''} {p.hwid or ''}".lower()
            keywords = ("usb", "uart", "ch340", "ch341", "cp210", "ftdi",
                        "prolific", "pl2303", "silicon labs", "arduino", "stlink")
            return (p.vid is not None and p.pid is not None) or any(word in details for word in keywords)

        labels = []
        self.port_map = {}
        for p in ports:
            description = (p.description or "串口设备").replace(f"({p.device})", "").strip()
            label = f"{p.device} · {description}"
            if is_usb_serial(p):
                label = "★ " + label
            labels.append(label)
            self.port_map[label] = p.device

        values_changed=tuple(self.ports["values"])!=tuple(labels)
        desired_height=max(1,len(labels))
        height_changed=int(self.ports.cget("height"))!=desired_height
        if height_changed:self.ports.configure(height=desired_height)
        if values_changed:
            self.ports["values"] = labels
        preserved = next((label for label in labels if self.port_map[label] == previous_device), None)
        newly_added=next((label for label in labels if self.port_map[label] not in previous_devices),None)
        if preserved:
            if self.portname.get()!=preserved:self.portname.set(preserved)
        elif newly_added and not self.port:
            if self.portname.get()!=newly_added:self.portname.set(newly_added)
        elif labels:
            if self.portname.get()!=labels[0]:self.portname.set(labels[0])
        else:
            if self.portname.get():self.portname.set("")
        if values_changed or height_changed:self._refresh_open_port_dropdown()

        if self.port:
            self.status.set(f"已连接 {self.port.name} @ {self.baud.get()} · RX {len(self.rx)} 字节")
        elif ports:
            self.status.set(f"检测到 {len(ports)} 个串口")
        else:
            self.status.set("未发现串口设备")

    def _auto_refresh_ports(self):
        self.refresh()
        self._port_refresh_after=self.after(350,self._auto_refresh_ports)

    def _refresh_open_port_dropdown(self):
        popdown=f"{self.ports._w}.popdown"
        try:
            if self.tk.call("winfo","exists",popdown) and self.tk.call("winfo","viewable",popdown):
                self.tk.call("ttk::combobox::ConfigureListbox",self.ports._w)
                self.tk.call("update","idletasks")
                self.tk.call("ttk::combobox::PlacePopdown",self.ports._w,popdown)
        except tk.TclError:
            pass

    def _serial_parameters(self):
        parity={"None":serial.PARITY_NONE,"Even":serial.PARITY_EVEN,"Odd":serial.PARITY_ODD}[self.parity.get()]
        stopbits={"1":serial.STOPBITS_ONE,"1.5":serial.STOPBITS_ONE_POINT_FIVE,"2":serial.STOPBITS_TWO}[self.stopbits.get()]
        baudrate=int(self.baud.get())
        if baudrate<=0:raise ValueError("波特率必须大于 0。")
        return {"baudrate":baudrate,"bytesize":int(self.bits.get()),"parity":parity,
                "stopbits":stopbits,"timeout":.1,"write_timeout":1}

    def _schedule_serial_reconfigure(self,_event=None):
        if not self.port or not getattr(self.port,"is_open",False):return
        if self._serial_update_after is not None:
            try:self.after_cancel(self._serial_update_after)
            except tk.TclError:pass
        self._serial_update_after=self.after(180,self._apply_serial_reconfigure)

    def _restore_serial_controls(self):
        if not self.port:return
        self.baud.set(str(self.port.baudrate))
        self.bits.set(str(self.port.bytesize))
        self.parity.set({serial.PARITY_NONE:"None",serial.PARITY_EVEN:"Even",serial.PARITY_ODD:"Odd"}.get(self.port.parity,"None"))
        self.stopbits.set({1.0:"1",1.5:"1.5",2.0:"2"}.get(float(self.port.stopbits),str(self.port.stopbits)))
        current_label=next((label for label,device in self.port_map.items() if device==self.port.name),None)
        if current_label:self.portname.set(current_label)

    def _apply_serial_reconfigure(self):
        self._serial_update_after=None
        if not self.port or not getattr(self.port,"is_open",False):return
        try:
            selected_port=self.port_map.get(self.portname.get())
            if not selected_port:raise ValueError("请选择仍然存在的串口设备。")
            parameters=self._serial_parameters()
            if selected_port==self.port.name:
                old=(self.port.baudrate,self.port.bytesize,self.port.parity,self.port.stopbits)
                try:
                    self.port.baudrate=parameters["baudrate"]
                    self.port.bytesize=parameters["bytesize"]
                    self.port.parity=parameters["parity"]
                    self.port.stopbits=parameters["stopbits"]
                except Exception:
                    self.port.baudrate,self.port.bytesize,self.port.parity,self.port.stopbits=old
                    raise
            else:
                new_port=serial.Serial(selected_port,**parameters)
                old_port=self.port
                old_reader=self.reader_thread
                self.stop_reader.set()
                try:old_port.close()
                except Exception:pass
                if old_reader and old_reader.is_alive():old_reader.join(timeout=1.0)
                self.port=new_port
                self.stop_reader.clear()
                self.reader_thread=threading.Thread(target=self.reader,args=(new_port,),daemon=True)
                self.reader_thread.start()
            self._mark_wave_gap()
            if hasattr(self,"_parse_pending"):
                self._parse_pending.clear()
                self._parse_offset=len(self.rx)
            self.status.set(f"已连接 {self.port.name} @ {parameters['baudrate']} · RX {len(self.rx)} 字节")
        except Exception as error:
            self._restore_serial_controls()
            messagebox.showerror("串口参数更新失败",str(error),parent=self)

    def connect(self):
        if self.port:
            self._stop_repeat_send()
            self._mark_wave_gap()
            self.stop_reader.set()
            try: self.port.close()
            except Exception: pass
            self.port=None
            self.conn.config(text="连接")
            self.status.set("未连接")
            return
        if serial is None:
            messagebox.showerror("缺少依赖","运行 python -m pip install -r requirements.txt")
            return
        port_name=self.port_map.get(self.portname.get())
        if not port_name:
            messagebox.showwarning("请选择串口","请刷新并选择一个串口设备。")
            return
        try:
            self.port=serial.Serial(port_name,**self._serial_parameters())
        except Exception as e:
            self.port=None
            messagebox.showerror("连接失败",str(e))
            return
        self.stop_reader.clear()
        self._mark_wave_gap()
        self.reader_thread=threading.Thread(target=self.reader,args=(self.port,),daemon=True)
        self.reader_thread.start()
        self.conn.config(text="断开")
        self.status.set(f"已连接 {port_name} @ {self.baud.get()} · RX 0 字节")

    def reader(self,port):
        while not self.stop_reader.is_set():
            try:
                n=port.in_waiting
                data=port.read(n if n else 1)
                if data: self.q.put(data)
            except Exception as e:
                self.q.put(("error",str(e),port))
                break

    def poll(self):
        changed=False
        batch=bytearray()
        while True:
            try: item=self.q.get_nowait()
            except queue.Empty: break
            if isinstance(item,tuple):
                error_port=item[2] if len(item)>2 else self.port
                if error_port is self.port:
                    self._stop_repeat_send()
                    self._mark_wave_gap()
                    self.status.set("接收错误："+item[1])
                    self.stop_reader.set()
                    try: self.port.close()
                    except Exception: pass
                    self.port=None
                    self.conn.config(text="连接")
            else:
                self.rx.extend(item)
                batch.extend(item)
                if len(self.rx)>262144: del self.rx[:-262144]
                changed=True
        if batch:
            stamp=datetime.now().strftime("%H:%M:%S.%f")[:-3]
            self._store_log_chunk(stamp,bytes(batch),"rx")
        if changed:
            self.refresh_view()
            if self.port:
                self.status.set(f"已连接 {self.port.name} @ {self.baud.get()} · RX {len(self.rx)} 字节")
        if self.port and self.reader_thread and not self.reader_thread.is_alive():
            self._mark_wave_gap()
            self.status.set("接收线程已停止；请断开后重新连接")
        self.after(50,self.poll)

    def _store_log_chunk(self,stamp,data,direction):
        self.rx_chunks.append((stamp,data,direction))
        if len(self.rx_chunks)>5000:
            remove_count=len(self.rx_chunks)-4500
            del self.rx_chunks[:remove_count]
            self._trim_visible_log(remove_count)

    def _trim_visible_log(self,count):
        if count<=0:return
        if count>self._view_chunk_count or count>len(self._view_chunk_lines):
            self.refresh_view(full=True)
            return
        old_lines=[self._view_chunk_lines.popleft() for _ in range(count)]
        self._view_chunk_count-=count
        self.out_hex.configure(state="normal")
        self.out_text.configure(state="normal")
        self.out_hex.delete("1.0",f"{sum(pair[0] for pair in old_lines)+1}.0")
        self.out_text.delete("1.0",f"{sum(pair[1] for pair in old_lines)+1}.0")
        self.out_hex.configure(state="disabled")
        self.out_text.configure(state="disabled")

    def refresh_view(self,full=False):
        for widget in (self.out_hex,self.out_text):
            widget.configure(state="normal")
        if full:
            for widget in (self.out_hex,self.out_text):
                widget.delete("1.0","end")
            self._view_chunk_count=0
            self._view_chunk_lines.clear()
        start=self._view_chunk_count
        for entry in self.rx_chunks[start:]:
            stamp,data,direction=entry if len(entry)==3 else (*entry,"rx")
            hex_payload=" ".join(f"{b:02X}" for b in data)
            # In text mode, UART line terminators should behave like terminal
            # line breaks instead of being rendered as the literal characters \\r/\\n.
            text_payload=data.decode("utf-8",errors="replace").replace("\r\n","\n").replace("\r","\n")
            label="发送→" if direction=="tx" else "接收←"
            tags=("tx",) if direction=="tx" else ()
            self.out_hex.insert("end",f"[{stamp}] {label} {hex_payload}\n",tags)
            # Keep the payload's line break and the log entry separator separate.
            # A trailing CRLF therefore leaves a visible blank line before the next entry.
            text_line=f"[{stamp}] {label} {text_payload}\n"
            self.out_text.insert("end",text_line,tags)
            self._view_chunk_lines.append((1,max(1,text_line.count("\n"))))
            self._view_chunk_count+=1
        for widget in (self.out_hex,self.out_text):
            widget.configure(state="disabled")
        self.out_hex.see("end")
        self.out_text.see("end")

    def clear(self):
        self.rx.clear()
        self.rx_chunks.clear()
        if hasattr(self,"_parse_pending"):
            self._parse_pending.clear()
            self._parse_offset=0
        self.refresh_view(full=True)
        self.settext(self.parsed,"接收缓冲已清空。")

    def send(self):
        if not self.port:
            messagebox.showwarning("串口未连接","请先连接串口。")
            return False
        raw=self.sendbox.get("1.0","end-1c")
        try:
            mode=self.sendmode.get()
            if mode=="HEX":
                data=bytes(int(x,16) for x in raw.replace(","," ").replace("，"," ").split())
            elif mode=="数据帧":
                data=self._frame_send_bytes()
            else:
                data=raw.encode("utf-8")
            if mode=="文本" and self.crlf.get(): data+=b"\r\n"
            if data:
                self.port.write(data)
                stamp=datetime.now().strftime("%H:%M:%S.%f")[:-3]
                self._store_log_chunk(stamp,data,"tx")
                self.refresh_view()
                self.status.set(f"已发送 {len(data)} 字节 · RX {len(self.rx)} 字节")
                return True
            messagebox.showwarning("发送内容为空","请先输入要发送的内容。")
            return False
        except ValueError as e:
            if self.sendmode.get()=="数据帧":
                messagebox.showerror("数据帧无效",str(e),parent=self)
            else:
                messagebox.showerror("HEX格式错误",f"请用空格分隔字节，例如 03 E8\n{e}")
            return False
        except Exception as e:
            messagebox.showerror("发送失败",str(e))
            return False

    def _toggle_repeat_send(self):
        if not self.repeat_send.get():
            self._stop_repeat_send()
            return
        if not self.port or not getattr(self.port,"is_open",False):
            self.repeat_send.set(False)
            messagebox.showwarning("串口未连接","请先连接串口，再开启循环发送。",parent=self)
            return
        try:
            interval=float(self.repeat_interval.get())
            if not 0.1<=interval<=3600: raise ValueError("循环发送间隔需在 0.1 到 3600 秒之间。")
        except ValueError as error:
            self.repeat_send.set(False)
            messagebox.showwarning("循环间隔无效",str(error),parent=self)
            return
        if self.send():self._schedule_repeat_send()
        else:self.repeat_send.set(False)

    def _schedule_repeat_send(self):
        if not self.repeat_send.get():return
        try:
            interval=float(self.repeat_interval.get())
            if not 0.1<=interval<=3600: raise ValueError()
        except ValueError:
            self._stop_repeat_send()
            messagebox.showwarning("循环间隔无效","循环发送间隔需在 0.1 到 3600 秒之间。",parent=self)
            return
        self._send_after=self.after(int(interval*1000),self._repeat_send_tick)

    def _repeat_send_tick(self):
        self._send_after=None
        if not self.repeat_send.get():return
        if not self.port or not getattr(self.port,"is_open",False) or not self.send():
            self._stop_repeat_send()
            return
        self._schedule_repeat_send()

    def _stop_repeat_send(self):
        if self._send_after is not None:
            try:self.after_cancel(self._send_after)
            except tk.TclError:pass
            self._send_after=None
        if hasattr(self,"repeat_send"):
            self.repeat_send.set(False)

    def close(self):
        self._stop_repeat_send()
        if getattr(self,"_frame_send_layout_after",None) is not None:
            try:self.after_cancel(self._frame_send_layout_after)
            except tk.TclError:pass
        if self._serial_update_after is not None:
            try:self.after_cancel(self._serial_update_after)
            except tk.TclError:pass
        if getattr(self,"_port_refresh_after",None) is not None:
            try:self.after_cancel(self._port_refresh_after)
            except tk.TclError:pass
        self.stop_reader.set()
        try:
            if self.port: self.port.close()
        except Exception: pass
        self.destroy()
