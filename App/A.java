import 'dart:convert'; // Import JSON encoding library
import 'package:flutter/material.dart';

void main() {
  runApp(const MyApp());
}

class MyApp extends StatelessWidget {
  const MyApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Flutter Demo',
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(seedColor: Colors.deepPurple),
        useMaterial3: true,
      ),
      home: const MyHomePage(title: 'Shopping Trolley'),
    );
  }
}

class MyHomePage extends StatefulWidget {
  const MyHomePage({super.key, required this.title});
  final String title;

  @override
  State<MyHomePage> createState() => _MyHomePageState();
}

class _MyHomePageState extends State<MyHomePage> {
  // List of items and their quantities
  final List<Item> _items = [
    Item(name: "Apples", quantity: 0),
    Item(name: "Bananas", quantity: 0),
    Item(name: "Oranges", quantity: 0),
    // Add more items as needed
  ];

  void _incrementQuantity(int index) {
    setState(() {
      _items[index].quantity++;
    });
  }

  void _decrementQuantity(int index) {
    setState(() {
      if (_items[index].quantity > 0) _items[index].quantity--;
    });
  }

  void _sendDataToServer() {
    // Convert items to a JSON string
    List<Map<String, dynamic>> itemList = _items
        .map((item) => {'name': item.name, 'quantity': item.quantity})