import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication,QComboBox,QStyledItemDelegate,QListView,QLineEdit
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from toolbox import ToolboxWindow


class SharedControlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def test_all_pages_use_shared_popup_without_changing_item_data(self):
        window=ToolboxWindow();window.show()
        try:
            for page in range(4):
                window.select_page(page);self.app.processEvents()
                combos=window.pages.widget(page).findChildren(QComboBox)
                self.assertTrue(combos)
                combo=next(c for c in combos if c.isVisible() and c.isEnabled())
                before=[combo.itemData(i) for i in range(combo.count())]
                combo.showPopup();self.app.processEvents();self.assertTrue(combo.view().isVisible())
                self.assertGreaterEqual(combo.view().sizeHintForRow(0),32)
                combo.hidePopup();self.assertEqual(before,[combo.itemData(i) for i in range(combo.count())])
                self.assertTrue(combo.property('vtSharedReady'))
            ref=window.defect.reference;auto=window.defect.auto_reference
            auto.setChecked(True);self.assertFalse(ref.isEnabled());auto.setChecked(False);self.assertTrue(ref.isEnabled())
        finally:window.close();self.app.processEvents()

    def test_dynamic_editable_combo_keeps_custom_view_and_delegate(self):
        window=ToolboxWindow();window.show();window.select_page(2);self.app.processEvents()
        try:
            dynamic=QComboBox(window.script);view=QListView();delegate=QStyledItemDelegate(view)
            view.setItemDelegate(delegate);dynamic.setView(view);dynamic.setEditable(True)
            dynamic.addItem('规则A',17);dynamic.addItem('规则B',23);dynamic.show();self.app.processEvents();self.app.processEvents()
            self.assertIs(dynamic.view(),view);self.assertIs(view.itemDelegate(),delegate)
            self.assertEqual(dynamic.itemData(1),23);dynamic.setEditText('自定义值');self.assertEqual(dynamic.currentText(),'自定义值')
            dynamic.lineEdit().setReadOnly(True);QTest.keyClicks(dynamic.lineEdit(),'ignored');self.assertEqual(dynamic.currentText(),'自定义值')
            self.assertTrue(dynamic.property('vtSharedReady'))
        finally:window.close();self.app.processEvents()

    def test_application_style_change_after_closing_toolbox(self):
        window=ToolboxWindow();window.show();self.app.processEvents();window.close()
        self.app.setStyle('Fusion');self.app.processEvents()
        next_window=ToolboxWindow();next_window.show();next_window.select_page(3);self.app.processEvents()
        try:
            combo=next_window.camera.controls['kind'];combo.showPopup();self.app.processEvents()
            self.assertTrue(combo.view().isVisible());combo.hidePopup()
        finally:next_window.close();self.app.processEvents()


if __name__=='__main__':unittest.main()
