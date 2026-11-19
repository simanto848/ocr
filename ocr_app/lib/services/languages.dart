/// Language choices shared by both extraction modes.
class LanguageChoice {
  final String value;
  final String label;

  const LanguageChoice(this.value, this.label);

  static const all = [
    LanguageChoice('auto', 'Auto — English + বাংলা + हिन्दी'),
    LanguageChoice('en', 'English only'),
    LanguageChoice('bn', 'বাংলা (Bangla) only'),
    LanguageChoice('hi', 'हिन्दी (Hindi) only'),
    LanguageChoice('mixed', 'English + বাংলা + हिन्दी'),
  ];

  /// Value understood by the Python server's /api/upload `lang` field.
  static String serverValue(String choice) => all.any((l) => l.value == choice) ? choice : 'auto';

  /// Value understood by Tesseract's `-l` flag (on-device OCR).
  static String tessdataValue(String choice) => switch (choice) {
        'en' => 'eng',
        'bn' => 'ben',
        'hi' => 'hin',
        _ => 'eng+ben+hin',
      };
}
