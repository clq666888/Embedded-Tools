import colorsys
import re
import time
import tkinter as tk
from tkinter import ttk, messagebox, colorchooser


class WaveformMixin:
    @staticmethod
    def _default_wave_color(index):
        palette=("#168AAD","#E76F51","#2A9D8F","#8E5CC2","#E9A11B","#D9488B",
                 "#577590","#55A630","#BC4749","#0077B6","#6D597A","#7F5539")
        if index<len(palette):return palette[index]
        hue=(index*0.618033988749895)%1.0
        red,green,blue=colorsys.hsv_to_rgb(hue,0.72,0.78)
        return "#{:02X}{:02X}{:02X}".format(round(red*255),round(green*255),round(blue*255))

    @staticmethod
    def _valid_wave_color(color):
        return isinstance(color,str) and re.fullmatch(r"#[0-9A-Fa-f]{6}",color) is not None

    def _ensure_field_colors(self):
        used=set()
        for field in self.fields:
            color=field.get("color")
            if not self._valid_wave_color(color) or color.upper() in used:
                index=len(used)
                color=self._default_wave_color(index)
                while color.upper() in used:
                    index+=1
                    color=self._default_wave_color(index)
                field["color"]=color
            used.add(field["color"].upper())

    def open_waveform(self):
        if self._wave_window is not None and self._wave_window.winfo_exists():
            self._wave_window.deiconify()
            self._wave_window.lift()
            self._sync_wave_controls()
            self._schedule_wave_redraw(0)
            return

        win=tk.Toplevel(self)
        self._wave_window=win
        win.title("UART 波形分析")
        win.geometry("1100x720")
        win.minsize(760,480)
        win.transient(self)
        win.protocol("WM_DELETE_WINDOW",self._close_waveform)
        self._wave_samples.clear()
        self._wave_time_origin=time.monotonic()
        self._wave_break_next_sample=False
        self._wave_view_span=30.0
        self._wave_view_start=0.0
        self._wave_view_end=30.0
        self._wave_fit=False
        self._wave_manual_view=False
        win.columnconfigure(0,weight=1)
        win.rowconfigure(1,weight=1)

        toolbar=ttk.LabelFrame(win,text="显示字段",padding=(8,5))
        toolbar.grid(row=0,column=0,sticky="ew",padx=10,pady=(10,6))
        toolbar.columnconfigure(0,weight=1)
        self._wave_controls=ttk.Frame(toolbar)
        self._wave_controls.grid(row=0,column=0,sticky="ew")
        wave_actions=ttk.Frame(toolbar)
        wave_actions.grid(row=0,column=1,sticky="e",padx=(8,0))
        self._wave_auto_button=ttk.Button(wave_actions,text="Auto",command=self._wave_auto)
        self._wave_auto_button.pack(side="left")

        graph=ttk.Frame(win)
        graph.grid(row=1,column=0,sticky="nsew",padx=10)
        graph.rowconfigure(0,weight=1)
        graph.columnconfigure(0,weight=1)
        self._wave_canvas=tk.Canvas(graph,bg="#ffffff",highlightthickness=1,highlightbackground="#dce3eb")
        self._wave_canvas.grid(row=0,column=0,sticky="nsew")
        self._wave_canvas.bind("<Configure>",lambda _event:self._schedule_wave_redraw(0))
        self._wave_canvas.bind("<MouseWheel>",self._wave_zoom)
        self._wave_canvas.bind("<ButtonPress-1>",self._wave_pan_start)
        self._wave_canvas.bind("<B1-Motion>",self._wave_pan_move)
        self._wave_canvas.bind("<Motion>",self._wave_hover_move)
        self._wave_canvas.bind("<Leave>",self._wave_hover_leave)

        ttk.Label(win,text="时间从打开波形窗口起算（0 秒）；滚轮缩放时间轴，按住鼠标左键拖动；多字段共用原值纵轴。",
                  foreground="#657487",anchor="w").grid(row=2,column=0,sticky="ew",padx=12,pady=(6,10))
        self._sync_wave_controls()
        self._schedule_wave_redraw(0)

    def _close_waveform(self):
        if self._wave_redraw_after is not None:
            try:self.after_cancel(self._wave_redraw_after)
            except tk.TclError:pass
            self._wave_redraw_after=None
        win=self._wave_window
        self._wave_window=None
        if win is not None:
            try:win.destroy()
            except tk.TclError:pass

    def _sync_wave_controls(self):
        win=self._wave_window
        if win is None or not win.winfo_exists():return
        for child in self._wave_controls.winfo_children():child.destroy()
        names={field["name"] for field in self.fields}
        old_vars=self._wave_vars
        previously_known=names.intersection(old_vars)
        self._wave_vars={name:var for name,var in old_vars.items() if name in names}
        if not self.fields:
            ttk.Label(self._wave_controls,text="请先添加字段定义。",foreground="#657487").pack(side="left")
        else:
            ttk.Label(self._wave_controls,text="选择字段：").pack(side="left",padx=(0,8))
            for index,field in enumerate(self.fields):
                name=field["name"]
                var=self._wave_vars.get(name)
                if var is None:
                    var=tk.BooleanVar(value=(not previously_known and index==0))
                    self._wave_vars[name]=var
                item=ttk.Frame(self._wave_controls)
                item.pack(side="left",padx=(0,12))
                ttk.Checkbutton(item,text=name,variable=var,
                    command=lambda:self._schedule_wave_redraw(0)).pack(side="left")
                color=field.get("color",self._default_wave_color(index))
                tk.Button(item,text="",width=2,relief="solid",bd=1,bg=color,activebackground=color,
                    cursor="hand2",command=lambda field_name=name:self._choose_wave_color(field_name)).pack(side="left",padx=(2,0))
        self._schedule_wave_redraw(0)

    def _choose_wave_color(self,name):
        field=next((item for item in self.fields if item["name"]==name),None)
        if field is None:return
        chosen=colorchooser.askcolor(color=field.get("color",self._default_wave_color(0)),
                                     title=f"选择“{name}”的波形颜色",parent=self._wave_window)[1]
        if not chosen:return
        chosen=chosen.upper()
        if any(other is not field and other.get("color","").upper()==chosen for other in self.fields):
            messagebox.showwarning("颜色已被使用","每个字段需要使用不同颜色，请为该字段选择另一种颜色。",parent=self._wave_window)
            return
        field["color"]=chosen
        self._sync_wave_controls()
        self._schedule_wave_redraw(0)

    def _wave_latest_time(self):
        return self._wave_samples[-1]["time"] if self._wave_samples else 0.0

    def _wave_current_time_range(self):
        if self._wave_manual_view:
            return self._wave_view_start,self._wave_view_end
        latest=self._wave_latest_time()
        if self._wave_fit:
            return 0.0,max(10.0,latest)
        span=max(0.2,self._wave_view_span)
        end=max(span,latest)
        return max(0.0,end-span),end

    def _wave_values_in_range(self,name,start,end):
        return [sample["values"][name] for sample in self._wave_samples
                if start<=sample["time"]<=end and name in sample["values"]]

    def _wave_auto(self):
        self._wave_fit=True
        self._wave_manual_view=False
        self._wave_view_start=0.0
        self._wave_view_end=max(10.0,self._wave_latest_time())
        self._wave_view_span=self._wave_view_end
        self._schedule_wave_redraw(0)

    def _wave_zoom(self,event):
        start,end=self._wave_current_time_range()
        span=end-start
        factor=0.8 if event.delta>0 else 1.25
        new_span=max(0.2,min(86400.0,span*factor))
        width=max(1,self._wave_canvas.winfo_width()-153)
        fraction=max(0.0,min(1.0,(event.x-125)/width))
        anchor=start+fraction*span
        new_start=max(0.0,anchor-fraction*new_span)
        self._wave_view_start=new_start
        self._wave_view_end=new_start+new_span
        self._wave_view_span=new_span
        self._wave_fit=False
        self._wave_manual_view=True
        self._schedule_wave_redraw(0)
        return "break"

    def _wave_pan_start(self,event):
        self._wave_drag_start_x=event.x
        self._wave_drag_start_range=self._wave_current_time_range()

    def _wave_pan_move(self,event):
        start,end=self._wave_drag_start_range
        span=end-start
        width=max(1,self._wave_canvas.winfo_width()-153)
        shift=-(event.x-self._wave_drag_start_x)*span/width
        new_start=max(0.0,start+shift)
        self._wave_view_start=new_start
        self._wave_view_end=new_start+span
        self._wave_view_span=span
        self._wave_fit=False
        self._wave_manual_view=True
        self._schedule_wave_redraw(0)

    def _wave_hover_leave(self,_event=None):
        canvas=getattr(self,"_wave_canvas",None)
        if canvas is not None:
            canvas.delete("wave-hover")

    def _wave_hover_move(self,event):
        canvas=self._wave_canvas
        canvas.delete("wave-hover")
        points=getattr(self,"_wave_hover_points",())
        if not points:return
        best=None
        for point in points:
            distance=(point[0]-event.x)**2+(point[1]-event.y)**2
            if best is None or distance<best[0]:best=(distance,point)
        if best is None or best[0]>18**2:return
        _,(x,y,name,stamp,value,color)=best
        label=f"{name}  {stamp:.3f} 秒  {value}"
        text=canvas.create_text(event.x+14,event.y-14,text=label,anchor="sw",fill="#17212b",
                                font=("Microsoft YaHei UI",10,"bold"),tags=("wave-hover",))
        bounds=canvas.bbox(text)
        if bounds:
            canvas.create_rectangle(bounds[0]-6,bounds[1]-4,bounds[2]+6,bounds[3]+4,
                                    fill="#fffbe6",outline=color,width=1,tags=("wave-hover",))
            canvas.tag_raise(text)
        canvas.create_oval(x-5,y-5,x+5,y+5,fill="#ffffff",outline=color,width=2,
                           tags=("wave-hover",))

    def _schedule_wave_redraw(self,delay=120):
        if self._wave_window is None or not self._wave_window.winfo_exists():return
        if self._wave_redraw_after is not None:
            try:self.after_cancel(self._wave_redraw_after)
            except tk.TclError:pass
        self._wave_redraw_after=self.after(delay,self._draw_waveform)

    def _draw_waveform(self):
        self._wave_redraw_after=None
        if self._wave_window is None or not self._wave_window.winfo_exists():return
        canvas=self._wave_canvas
        canvas.delete("all")
        width=max(canvas.winfo_width(),760)
        height=max(canvas.winfo_height(),400)
        if not self.fields:
            canvas.create_text(width/2,height/2,text="请先在数据解析页添加字段定义。",fill="#657487",
                               font=("Microsoft YaHei UI",11))
            return
        selected=[field for field in self.fields
                  if self._wave_vars.get(field["name"]) is not None and self._wave_vars[field["name"]].get()]
        if not selected:
            self._wave_hover_points=[]
            canvas.create_text(width/2,height/2,text="请至少勾选一个字段以显示波形。",fill="#657487",
                               font=("Microsoft YaHei UI",11))
            return
        start,end=self._wave_current_time_range()
        if end<=start:end=start+1.0
        left,right=125,width-28
        legend_rows=max(1,(len(selected)+2)//3)
        plot_top,plot_bottom=45+legend_rows*24,height-76
        plot_width=max(1,right-left)
        columns=min(3,len(selected))
        item_width=max(1,plot_width/columns)
        field_series={}
        for index,field in enumerate(selected):
            name=field["name"]
            series=[sample for sample in self._wave_samples
                    if start-1.0<=sample["time"]<=end+1.0 and name in sample["values"]]
            max_points=max(600,width*2)
            segments=[]
            segment=[]
            for sample in series:
                if sample.get("break_before") and segment:
                    segments.append(segment)
                    segment=[]
                segment.append(sample)
            if segment:segments.append(segment)
            if sum(map(len,segments))>max_points and segments:
                remaining=max_points
                reduced=[]
                for segment_index,segment in enumerate(segments):
                    budget=max(1,remaining-(len(segments)-segment_index-1))
                    if len(segment)>budget and budget>1:
                        step=(len(segment)-1)/(budget-1)
                        segment=[segment[min(len(segment)-1,int(point*step))] for point in range(budget)]
                    elif len(segment)>budget:
                        segment=segment[-1:]
                    reduced.append(segment)
                    remaining=max(0,remaining-len(segment))
                segments=reduced
            values=self._wave_values_in_range(name,start,end)
            if not values:
                values=[sample["values"][name] for sample in self._wave_samples if name in sample["values"]]
            current=next((sample["values"][name] for sample in reversed(self._wave_samples)
                          if name in sample["values"]),None)
            low_value=min(values) if values else None
            high_value=max(values) if values else None
            field_series[name]=(segments,values,current,low_value,high_value)
            row,column=divmod(index,columns)
            x=left+column*item_width
            y=24+row*24
            color=field.get("color",self._default_wave_color(index))
            canvas.create_line(x,y,x+19,y,fill=color,width=3)
            range_text=(f"{low_value:.5g}–{high_value:.5g}" if values else "等待数据")
            canvas.create_text(x+25,y,text=f"{name}  当前 {current if current is not None else '—'}  范围 {range_text}",
                               anchor="w",fill=color,font=("Microsoft YaHei UI",9,"bold"))

        all_values=[value for _,values,_,_,_ in field_series.values() for value in values]
        if all_values:
            low=min(all_values);high=max(all_values)
            padding=max(abs(low)*0.05,1) if low==high else (high-low)*0.08
            low-=padding;high+=padding
        else:
            low,high=-1.0,1.0

        canvas.create_text(15,(plot_top+plot_bottom)/2,text="数值（原值）",angle=90,
                           fill="#657487",font=("Microsoft YaHei UI",9))
        for index in range(11):
            fraction=index/10
            y=plot_top+fraction*(plot_bottom-plot_top)
            tick=high-fraction*(high-low)
            canvas.create_line(left,y,right,y,fill="#e5ebf1" if index in (0,5,10) else "#f0f3f6")
            canvas.create_text(left-10,y,text=f"{tick:.5g}",anchor="e",fill="#657487",font=("Consolas",9))
        for index in range(6):
            fraction=index/5
            x=left+fraction*plot_width
            elapsed=start+fraction*(end-start)
            canvas.create_line(x,plot_top,x,plot_bottom,fill="#edf1f5")
            canvas.create_text(x,plot_bottom+21,text=f"{elapsed:.1f}",anchor="center",fill="#657487",font=("Consolas",9))

        has_data=False
        self._wave_hover_points=[]
        for field in selected:
            segments,values,current,_,_=field_series[field["name"]]
            if not segments:continue
            has_data=True
            color=field.get("color",self._default_wave_color(0))
            for segment in segments:
                points=[]
                for sample in segment:
                    stamp=sample["time"]
                    value=sample["values"][field["name"]]
                    x=left+(stamp-start)/(end-start)*plot_width
                    y=plot_bottom-(value-low)/(high-low)*(plot_bottom-plot_top)
                    points.extend((x,y))
                    self._wave_hover_points.append((x,y,field["name"],stamp,value,color))
                if len(points)>=4:
                    canvas.create_line(*points,fill=color,width=2,tags=(f"wave:{field['name']}",))
                elif len(points)==2:
                    x,y=points
                    canvas.create_oval(x-4,y-4,x+4,y+4,fill=color,outline=color,tags=(f"wave:{field['name']}",))
        if not has_data:
            canvas.create_text(width/2,(plot_top+plot_bottom)/2,text="等待完整数据帧……",fill="#8a98a8",
                               font=("Microsoft YaHei UI",11))
        canvas.create_text((left+right)/2,height-20,text="时间（秒，从 0 开始）",fill="#425466",
                           font=("Microsoft YaHei UI",9))
