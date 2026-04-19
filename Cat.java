public class Cat extends Animal {
    
    public Cat(String name, int age) {
        super(name, age);
    }
    
    @Override
    public void makeSound() {
        System.out.println("Meow!");
    }
    
    public void chaseMouse() {
        System.out.println(getName() + " is chasing a mouse");
    }
    
    public void groomSelf() {
        System.out.println(getName() + " is grooming");
    }
}
