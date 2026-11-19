import 'package:flutter_test/flutter_test.dart';

import 'package:ocr_app/main.dart';

void main() {
  testWidgets('app renders home screen', (WidgetTester tester) async {
    await tester.pumpWidget(const DocExtractApp());
    expect(find.text('DocExtract'), findsWidgets);
    expect(find.text('Extract text'), findsOneWidget);
  });
}
