public class Dog extends Animal {
    
    public Dog(String name, int age) {
        super(name, age);
    }
    
    @Override
    public void makeSound() {
        System.out.println("Woof!");
    }
    
    public void fetch() {
        System.out.println(getName() + " is fetching");
    }
    
    public void playWithBall() {
        System.out.println(getName() + " is playing with a ball");
    }
}
