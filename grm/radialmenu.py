import traceback
import math
import timeit
import logging
try:
    from Qt import QtWidgets, QtGui, QtCore
except:
    from PySide2 import QtWidgets, QtGui, QtCore


class RadialMenuItem(QtWidgets.QPushButton):
    '''
    Class for items of a radial menu. Supported types are
    positional and column items.

    Currently this is a QPushButton because QAction objects could
    only be placed in a column natively. These should eventually become
    QActionWidgets.

    item.position - The position associated with the item. If None the
                    item will display in the column menu.
    '''

    def __init__(self, position=None, text=None, invertHighlightTextColor=False):
        QtWidgets.QPushButton.__init__(self)
        self.position = position
        self.screen_ratio = get_screen_ratio()
        # Stop mouse events from affecting radial widgets
        self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents)
        if text:
            self.setText(text)
        self.item_height = 40.0 * self.screen_ratio

        # Use current highlight and light color
        highlight = self.palette().highlight().color().getRgb()
        bgcolor = self.palette().color(QtGui.QPalette.Background).name()
        self.h_text_color = self.palette().color(QtGui.QPalette.Text).getRgb()
        self.column_padding = 60 * self.screen_ratio
        if self.screen_ratio < 1.0:
            border = 1.0
        else:
            border = 2.0
        if position:
            style = """RadialMenuItem:hover{{
                            background-color:rgb({hr},{hg},{hb});
                            border: {border}px solid black;
                            font: bold
                        }}
                        RadialMenuItem{{
                            background-color:{bg};
                            border: {border}px solid black;
                        }}
                    """.format(hr=highlight[0], hg=highlight[1], hb=highlight[2],
                               bg=bgcolor,
                               border=border)
        else:
            style = """RadialMenuItem:hover{{
                            background-color:rgb({hr},{hg},{hb});
                            border: {border}px solid black;
                            font: bold;
                        }}
                        RadialMenuItem{{
                            background-color:{bg};
                            Text-align:left;
                            padding-left: {pad}px
                        }}
                    """.format(hr=highlight[0], hg=highlight[1], hb=highlight[2],
                               bg=bgcolor,
                               border=border,
                               pad=self.column_padding)

        self.style = style

        # Invert highlight color
        if invertHighlightTextColor:
            self.invertHighlightTextColor()

        self.setStyleSheet(self.style)
        self.checkBox = None
        self.function = None

    def connect(self, connect_function):
        self.function = connect_function

    def setCheckable(self, state):
        # ON
        if state:
            if self.checkBox:
                # checkBox already exists, just show it
                self.checkBox.show()
                return
            box = QtWidgets.QCheckBox(self)

            rect_width_height = 24 * self.screen_ratio
            rect_x_y = (self.item_height - rect_width_height) / 2

            rect = QtCore.QRect(rect_x_y, rect_x_y, rect_width_height, rect_width_height)
            box.setStyleSheet("QCheckBox::indicator {{ width: {}px; height: {}px;}}".format(
                               rect_width_height, rect_width_height))
            box.setGeometry(rect)
            box.setChecked(True)
            self.checkBox = box
        # OFF 
        else:
            if self.checkBox:
                self.checkBox.hide()

    def invertHighlightTextColor(self):
        self.h_text_color = (255 - self.h_text_color[0], 255 - self.h_text_color[1], 255 - self.h_text_color[2])

        self.style += """RadialMenuItem:hover{{
                        color:rgb({text_r}, {text_g}, {text_b})
                    }}
                """.format(text_r=self.h_text_color[0], text_g=self.h_text_color[1], text_b=self.h_text_color[2])
        self.setStyleSheet(self.style)

class RadialMenu(QtWidgets.QMenu):
    """
    Glossary
        item ----- A child widget which is displayed either in a cardinal
                   position or in a standard column menu.

        position - The 8 available cardinal directions that an item can
                   occupy. ['E', 'NE', 'N', 'NW', 'W', 'SW', 'S', 'SE]

        slice ---- One of the 16 divisions of the pie. Each slice is
                   22.5 degrees of the pie. As the cursor moves the menu
                   tracks what slice it is in. The slice is traced to 
                   its position and the position traces to its item. 

                   cursor(x,y)-->angle-->slice-->position-->item

                   A position is assocaited with two slices so its slices
                   can be given to its neighboring positions when the 
                   position is not in use (No item has mapped it). 
                   
                   For example, if only one item in the menu has
                   declared its position, it will eat up all the slices.
                   So no matter where the cursor is it will activate that
                   item.

    Data structure
        self.items    - contains the RaidialMenuItems that have been 
                        added to the menu.
        item.position - The position associated with item. If None the 
                        item will display in the column menu. 
        item.x        - The x and y coordinate of the top left corner
        item.y          of the item widget. This is assigned in the
                        addItem method.
    Item sizing
        item.width  - The setText method of the RadialItem calculates
                      the width of the text plus margins and assigns
                      it to item.width.
        item.height - The height does not need to change per item
                      so it is statically set in the __init__ of the
                      RadialItem.
    """
    def __init__(self, items=None):
        """
        Base custom QMenu
        """
        QtWidgets.QMenu.__init__(self)

        # Transparent is set to false because windows managers with no transparency
        #             do not work with transparency
        self.transparent = False
        # Draw cursor line - If true a line is draw from the center to the cursor
        self.draw_cursor_line = False

        # Window settings
        self.setWindowFlags(self.windowFlags() | QtCore.Qt.FramelessWindowHint | QtCore.Qt.NoDropShadowWindowHint)
        if self.transparent:
            self.setAttribute(QtCore.Qt.WA_TranslucentBackground)

        # Ratio for different screen sizes
        self.screen_ratio = get_screen_ratio()

        # Dimensions
        self.width = 1000 * self.screen_ratio
        self.height = 2000 * self.screen_ratio
        self.setFixedSize(self.width, self.height)

        # Timer for gestures
        self.timer = QtCore.QTimer()
        self.timer.setTimerType(QtCore.Qt.PreciseTimer)
        self.timer.timeout.connect(self.track_cursor)
        self.timer.setInterval(2)

        # Turns off when the cursor stops moving
        self.gesture = True

        # Main painter
        self.painter = QtGui.QPainter()
        # Mask painter
        self.painterMask = QtGui.QPainter()
        self.maskPixmap = QtGui.QPixmap(self.width, self.height)
        self.maskPixmap.fill(QtCore.Qt.white)
        # Track if mask has been set
        self.isMaskSet = False
        # Radius of origin circle
        self.originRadius = 8.0 * self.screen_ratio
        # Right click widget - Stores the mouse press event of the widget 
        #                      the menu is opened from when right clicked
        self.rightClickWidgetMousePressEvent = None
        # Stores which item is active
        self.activeItem = None
        # Pens
        gray = QtGui.QColor(128, 128, 128, 255)
        self.penOrigin = QtGui.QPen(gray,             5,  QtCore.Qt.SolidLine)
        self.penCursorLine = QtGui.QPen(gray,         3,  QtCore.Qt.SolidLine)
        self.penBlack = QtGui.QPen(QtCore.Qt.black,   2,  QtCore.Qt.SolidLine)
        self.penActive = QtGui.QPen(QtCore.Qt.red,    20, QtCore.Qt.SolidLine)
        self.penWhite = QtGui.QPen(QtCore.Qt.white,   5,  QtCore.Qt.SolidLine)
        self.transparentPen = QtGui.QPen(QtCore.Qt.transparent, 5000)

        ##########################################################
        # Items
        ##########################################################
        self.itemHeight = 40.0 * self.screen_ratio
        self.items = list()
        # Events sent to items to highlight them
        self.leaveButtonEvent = QtCore.QEvent(QtCore.QEvent.Leave)
        self.enterButtonEvent = QtCore.QEvent(QtCore.QEvent.Enter)

        # Radial item positions relative to center of radial menu
        r = self.screen_ratio
        self.position_xy = {'N':  [0*r,    - 100*r],
                            'S':  [0*r,      100*r],
                            'E':  [120*r,      0*r],
                            'W':  [-120*r ,    0*r],
                            'NE': [85*r,     -45*r],
                            'NW': [-85*r,    -45*r],
                            'SE': [85*r,      45*r],
                            'SW': [-85*r,     45*r]}
        # Slices - Each number represents a 22.5 degree slice, so each 
        #          position gets a 45 degree slice of the pie
        self.slices = {'E':  [15,  0],
                       'SE': [1,   2],
                       'S':  [3,   4],
                       'SW': [5,   6],
                       'W':  [7,   8],
                       'NW': [9,   10],
                       'N':  [11,  12],
                       'NE': [13,  14]}

        # Column widget
        self.column_widget = QtWidgets.QWidget()
        self.column_widget.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents)
        self.column_widget.setParent(self)
        self.column_widget.items = list()
        self.column_widget.rects = list()

        # Draw radial menu and its mask
        self.column_widget_rect = None
        self.paint_mask()

    def add_item(self, item=None, text=None):
        self.items.append(item)
        self.painterMask.begin(self.maskPixmap)

        if item.position:
            self.add_radial_item(item=item)
        else:
            self.add_column_item(item=item)

        self.painterMask.end()

    def add_radial_item(self, item=None):
        """
        """
        r = self.screen_ratio
        item.setParent(self)
        # Calculate the width of the text
        w, h = self.get_text_dimensions(item)
        width = w + (110*r) 
        height = self.itemHeight

        # Get base coordinates for position
        position = item.position
        x, y = self.position_xy[position]

        # Calculate top left x,y - Offset the positions because the 
        #                          buttons are drawn from the top left
        #                          corner and the stored positions are 
        #                          the center around the origin
        if 'W' in position:
            x -= width
            y -= height * .5
        if 'E' in position:
            y -= height * .5
        if 'N' == position:
            x -= width * .5
            y -= height
        if 'S' == position:
            x -= width * .5
        if 'NE' == position or 'NW' == position:
            y -= (20*self.screen_ratio)
        if 'SE' == position or 'SW' == position:
            y += (20*self.screen_ratio)

        # Widget rectangle
        x += self.width*.5
        y += self.height*.5
        # slice 
        self.update_slice_membership()
        # Define rect
        rect = QtCore.QRect(x, y, width, height)
        # Mask and draw
        self.painterMask.fillRect(rect, QtCore.Qt.black)
        item.setGeometry(rect)
        item.p_rect = rect

    def add_column_item(self, item=None):
        """
        Add items with no position specified so they show up
        in the column below the radial menu items

        Note: add_item method has already added the item
              being passed to the menu class self.items

        :param item:
        :return None:
        """
        # store how wide the column needs to be
        greatest_width = 0.0
        r = self.screen_ratio
        column_items = list()

        # Column width: Loop through all items in self.items and get
        #               the width of each column type item (no position specified)
        #               and track the greatest width with greatest_width
        #
        for cur_item in self.items:
            if not cur_item.position:
                column_items.append(cur_item)
                width = (self.get_text_dimensions(cur_item)[0] +
                         (cur_item.column_padding*2))
                if width > greatest_width:
                    greatest_width = width

        # Current item rect
        item_w = greatest_width
        h = self.itemHeight
        num_items = len(column_items)
        item.p_rect = QtCore.QRect(0, ((num_items-1)*(h-1)), item_w, h)

        # Update class item lists
        self.column_widget.rects.append(item.p_rect)
        self.column_widget.items.append(item)

        # MAIN COLUMN RECT: 
        w = greatest_width
        # Height is all the column items added
        h = ((h*num_items)-((num_items-1)*2))+3
        x = (self.width * .5)-(w * .5)
        y = (self.height * .5)+(170*r)

        # Mask and draw main column
        rect = QtCore.QRect(x, y, w, h)
        self.column_widget.setGeometry(rect)
        self.column_widget_rect = rect

        # Column mask for all items
        self.painterMask.fillRect(rect, QtCore.Qt.black)

        # Draw item on column
        item.setParent(self.column_widget)
        item.setGeometry(item.p_rect)

    @staticmethod
    def get_text_dimensions(item):
        """
        Find the width and hieght of the text label of the item
        :param item:
        :return width, height:
        """
        font = item.property('font')
        metric = QtGui.QFontMetrics(font)
        width = metric.width(item.text())
        height = metric.ascent() 
        return width, height

    def update_slice_membership(self):
        """
        Manage mapping pie slices to active positions
           This needs to be updated for all the slices
           each time an item is added or removed.
        
           Default slice membership is predefined for each 
           position in the menu __init__.  self.slices[position] 
           
           We loop through the positional items 
           and store their slices in slicesUsed.
        
           Now we need to loop through and give unused slices
           To the neighboring nearest active position.
        """

        slices_used = list()
        for item in self.items:
            position = item.position
            slices_used += self.slices[position]
            # Makes copy
            item.slices = list(self.slices[position])

        while len(slices_used) < 16:
            for item in self.items:
                # Find surrounding slices from the current items slices
                n = self.pie_last(item.slices[0])
                l = self.pie_next(item.slices[-1])
                # If slices is not used add it to its own slices
                if not n in slices_used:
                    item.slices.append(n)
                    slices_used.append(n)
                if not l in slices_used:
                    item.slices.append(l)
                    slices_used.append(l)

    def paint_mask(self):
        """
        Paint a mask for the items so it is transparent around them.
        """
        self.painterMask.begin(self.maskPixmap)

        # Center background circle - Where the origin dot
        #                            and line are drawn
        self.painterMask.setBrush(QtCore.Qt.black)
        # Origin offset - how big the visible circles is 
        #                 around the origin dot
        offset = 30*self.screen_ratio

        x = (self.width*.5)-((self.originRadius+offset)*.5)
        y = (self.height*.5)-((self.originRadius+offset)*.5)
        w = self.originRadius+offset
        h = w
        self.painterMask.drawEllipse(x, y, w, h)
        self.painterMask.end()

    def paintEvent(self, event):
        """
        Main paint event that handles the orginn circle and the line 
        from the origin to the moust direction.
        """
        try:
            # init painter - QPainting on self does not work outside this method
            self.painter.begin(self)

            cursor_pos = self.mapFromParent(QtGui.QCursor.pos())
            menu_center_pos = QtCore.QPoint(self.width*.5, self.height*.5)

            # Cursor line
            if self.draw_cursor_line:
                self.painter.setPen(self.penCursorLine)
                self.painter.drawLine(menu_center_pos, cursor_pos)
            # Origin circle - black outline
            offset = 2
            self.painter.setPen(self.penOrigin)
            self.painter.drawArc((self.width *.5)-(self.originRadius*.5),
                                 (self.height*.5)-(self.originRadius*.5),
                                 self.originRadius,  self.originRadius, 16, (360*16))
            # Origin circle - gray center
            self.painter.setPen(self.penBlack)
            self.painter.drawArc((self.width*.5)-((self.originRadius+offset)*.5),
                                 (self.height*.5)-((self.originRadius+offset)*.5),
                                 self.originRadius+offset, self.originRadius+offset, 16, (360*16))

            self.painter.end()
        except Exception as e:
            logging.exception(e)
            traceback.print_exc()

    def mouseMoveEvent(self, event):
        QtWidgets.QMenu.mouseMoveEvent(self, event)
        self.updateWidget()

    def updateWidget(self):
        self.livePos = QtGui.QCursor.pos()
        # Calculate how far has the mouse moved from origin
        length = math.hypot(self.startPos.x() - self.livePos.x(), 
                            self.startPos.y() - self.livePos.y())
        # Calculate angle of current cursor position to origin
        angle = self.angleFromPoints([self.startPos.x(), self.startPos.y()],
                                     [self.livePos.x(),  self.livePos.y()])
            
        # Item locations are broken into two 22.5 degree slices
        rad_slice = int(angle/22.5)
        ############################################################################
        # Highlight items - Highlighting is managed by sending leave and enter 
        #                   events to the items instead of explicingly setting the 
        #                   color.
        ############################################################################
        # Stores what item the user has chosen
        if self.activeItem:
            QtCore.QCoreApplication.sendEvent(self.activeItem, self.leaveButtonEvent)
            self.activeItem = None

        if not self.gesture and self.column_widget_rect:
            self.column_widget.setEnabled(True)
        cursor_pos = self.mapFromParent(self.livePos)
        # Check if mouse is outside the origin circle
        if length > 20:
            # Check cursor speed, when the cursor is moving quickly 
            # then we need to ignore the column items
            # Column items check
            if not self.gesture and self.column_widget_rect:
                if self.column_widget_rect.contains(cursor_pos):
                    cursor_pos = self.column_widget.mapFromGlobal(self.livePos)
                    for i in xrange(len(self.column_widget.rects)):
                        rect = self.column_widget.rects[i]
                        if rect.contains(cursor_pos):
                            self.activeItem = self.column_widget.items[i]
                            break
            # Radial items check 
            if not self.activeItem:
                for item in self.items:
                    position = item.position
                    if not position:
                        continue
                    rect = item.p_rect
                    # Clear any existing highlighting
                    QtCore.QCoreApplication.sendEvent(item, self.leaveButtonEvent)
                    # Radial rectangle check
                    if rect.contains(cursor_pos):
                        self.activeItem = item
                        break
                    # Slice check
                    if rad_slice in item.slices:
                        self.activeItem = item
        if self.activeItem:
            QtCore.QCoreApplication.sendEvent(self.activeItem, self.enterButtonEvent)
        # Call paint event
        self.update()

    def mouseReleaseEvent(self, event):
        QtWidgets.QMenu.mouseReleaseEvent(self, event)
        for item in self.items:
            QtCore.QCoreApplication.sendEvent(item, self.leaveButtonEvent)
        self.hide()

        # Run items function if it exists
        if self.activeItem:
            if self.activeItem.function:
                try:
                    self.activeItem.function()
                except:
                    traceback.print_exc()

        # Reset widgets
        self.activeItem = None
        self.column_widget.setEnabled(False)
        self.timer.stop()

    def timer_start(self):
        self.gesture = True
        self.startTime = timeit.default_timer()

        self.lastCursorPosition = None
        self.lastTime= None

        self.cursorChange = list()
        self.timeChange = list()
        self.timer.start()

    def angleFromPoints(self, p1=None, p2=None):
        """
        +X axis to the right is 0 Degrees
        +Y axis up is 90 degrees
        """
        radians = math.atan2(p2[1]-p1[1], p2[0]-p1[0])
        degrees = math.degrees(radians)
        if degrees < 0.0:
            degrees += 360.0
        return degrees

    def popup(self, pos=None):
        self.startPos = pos
        x = (pos.x()+(self.width*.5))-self.width 
        y = (pos.y()+(self.height*.5))-self.height 
        self.menuRect = QtCore.QRect(x, y, self.width, self.height)
        self.setGeometry(self.menuRect)
        self.show()

        # Apply mask, some apps may have overriden the QMenu class with mask
        # To override this we are setting the mask at popup time
        if not self.transparent and not self.isMaskSet:
            self.setMask(self.maskPixmap.createMaskFromColor(QtCore.Qt.white))
            self.isMaskSet = True

        self.timer_start()

    def right_click_popup(self, event):
        if event.buttons() != QtCore.Qt.RightButton:
            self.rightClickWidgetMousePressEvent(event)
            return()
        pos = QtGui.QCursor.pos()
        self.popup(pos)

    def right_click_connect(self, widget=None):
        self.rightClickWidgetMousePressEvent = widget.mousePressEvent
        widget.mousePressEvent = self.right_click_popup

    def left_click_popup(self, event):
        if event.buttons() != QtCore.Qt.LeftButton:
            self.leftClickWidgetMousePressEvent(event)
            return()
        pos = QtGui.QCursor.pos()
        self.popup(pos)

    def left_click_connect(self, widget=None):
        self.leftClickWidgetMousePressEvent = widget.mousePressEvent
        widget.mousePressEvent = self.left_click_popup

    def track_cursor(self):
        # Track cursor - When the mouse is first pressed start a timer (x).
        #                At each interval track how much the cursor has moved.
        #                If cursor speed is less then specified threshold
        #                turn of gesture mode and allow any column items to be
        #                selected.
        #       
        pos = QtGui.QCursor.pos()
        current_time = timeit.default_timer()
        # Time samples before judging if we have left gesture mode
        samples = 40
        # When the cursor speed is below this value turn gesture mode off
        cursor_speed_tolerance = .02

        if self.lastCursorPosition and self.gesture:
            time_change = current_time - self.lastTime
            change = math.hypot(self.lastCursorPosition.x() - pos.x(), 
                                self.lastCursorPosition.y() - pos.y())
            if len(self.cursorChange) < samples:
                self.cursorChange.append(change)
                self.timeChange.append(time_change)
            else:
                for i in xrange(samples-1):
                    self.cursorChange[i] = self.cursorChange[i+1]
                    self.timeChange[i] = self.timeChange[i+1]
                self.cursorChange[samples-1] = change
                self.timeChange[samples-1] = time_change

            cursor_speed = self.mean(self.cursorChange)
            # If the cursor speed is less than .01 pixels
            # when averaged over the number of samples then
            # Turn of gesture mode and allow all column items 
            # to be selected
            if len(self.cursorChange) > samples-1:
                if cursor_speed < cursor_speed_tolerance:
                    self.gesture = False
                    self.updateWidget()
                    self.timer.stop()

        self.lastCursorPosition = pos
        self.lastTime = current_time

    @staticmethod
    def pie_next(value, pie_max=15):
        if value == pie_max:
            return 0
        else:
            value += 1
            return value

    @staticmethod
    def pie_last(value, pie_max=15):
        if value == 0:
            return pie_max
        else:
            value -= 1
            return value

    @staticmethod
    def mean(numbers):
        return float(sum(numbers)) / max(len(numbers), 1)


def get_screen_ratio():
    """
    Find the logical dots per inch for the screens and calc
    a ratio from a fixed reference dpi.

    :return:
    """
    ref_dpi = 192.0

    screens = QtWidgets.QApplication.screens()
    if screens:
        current_dpi = screens[0].logicalDotsPerInch()
        screen_ratio = current_dpi/ref_dpi
        return screen_ratio
    else:
        return 1


