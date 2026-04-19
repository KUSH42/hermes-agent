public class Alium {
    protected String name;
    protected int age;
    protected String species;

    public Alium(String name, int age, String species) {
        this.name = name;
        this.age = age;
        this.species = species;
    }

    public String getName() {
        return name;
    }

    public int getAge() {
        return age;
    }

    public String getSpecies() {
        return species;
    }

    public void makeSound() {
        System.out.println("Woof! I'm " + name);
    }

    public void sleep() {
        System.out.println(name + " is sleeping");
    }

    public void eat() {
        System.out.println(name + " is eating");
    }

    public void wagTail() {
        System.out.println(name + "'s tail is wagging");
    }

    public void bark(int times) {
        for (int i = 0; i < times; i++) {
            System.out.print("Woof ");
        }
        System.out.println();
    }
}