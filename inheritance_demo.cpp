#include <iostream>
#include <string>
#include <vector>

using namespace std;

// Base class
class Base {
protected:
    string name;
    int value;

public:
    Base(string n, int val) : name(n), value(val) {}
    virtual ~Base() {}

    virtual void show() {
        cout << "Base: " << name << ", value: " << value << endl;
    }

    virtual int getValue() const { return value; }
};

// Derived class 1
class Derived1 : public Base {
private:
    string extraData;

public:
    Derived1(string n, int v, string ed) : Base(n, v), extraData(ed) {}

    void show() override {
        cout << "Derived1: " << name << ", value: " << value << ", extra: " << extraData << endl;
    }

    int getValue() const override {
        return value * 2;
    }

    void process() {
        cout << "Processing " << name << "..." << endl;
    }
};

// Derived class 2
class Derived2 : public Base {
private:
    vector<int> numbers;

public:
    Derived2(string n, int v, const vector<int>& nums) : Base(n, v), numbers(nums) {}

    void show() override {
        cout << "Derived2: " << name << ", value: " << value << ", count: " << numbers.size() << endl;
    }

    int getValue() const override {
        int sum = 0;
        for (int n : numbers) sum += n;
        return value + sum;
    }

    void addNumber(int num) {
        numbers.push_back(num);
    }
};

int main() {
    cout << "=== C++ Inheritance Demo ===" << endl << endl;

    Base* base1 = new Derived1("Item A", 10, "Alpha");
    Base* base2 = new Derived2("Item B", 20, {1, 2, 3, 4, 5});

    base1->show();
    base1->process();
    cout << "Value (x2): " << base1->getValue() << endl << endl;

    base2->show();
    base2->addNumber(6);
    cout << "Value (sum): " << base2->getValue() << endl << endl;

    // Polymorphism in action
    cout << "Polymorphic behavior:" << endl;
    Base* arr[] = {base1, base2};
    for (int i = 0; i < 2; i++) {
        arr[i]->show();
    }

    // Resource cleanup
    delete base1;
    delete base2;

    cout << "=== Demo Complete ===" << endl;

    return 0;
}