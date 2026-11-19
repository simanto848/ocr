import 'package:flutter/material.dart';

import 'screens/home_screen.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const DocExtractApp());
}

class DocExtractApp extends StatelessWidget {
  const DocExtractApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'DocExtract',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(seedColor: const Color(0xFF4A46C7)),
        useMaterial3: true,
      ),
      home: const HomeScreen(),
    );
  }
}
