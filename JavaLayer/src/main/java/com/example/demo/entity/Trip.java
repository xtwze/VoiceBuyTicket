package com.example.demo.entity;

import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import lombok.Data;

import java.time.LocalDate;

@Entity
@Data
public class Trip {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    private String departureStation;
    private String arrivalStation;
    private String departureTime;
    private String trainNumber;

    private String carriageType;

    private int totalSeats;
    private int availableSeats;
    private double price;

    private LocalDate departureDate;
}